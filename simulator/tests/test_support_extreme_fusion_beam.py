from __future__ import annotations

import dataclasses
import inspect
import pathlib
import sys
import time
import unittest


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.beam import (  # noqa: E402
    BeamNode,
    FutureSupportIngressBeam,
)
from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    CatalogStats,
    RootCatalog,
    RootRecord,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    ItemSpec,
    PlacementProposal,
    ValidatedRoot,
)
from agents.support_extreme_fusion_beam_exact_mask.proposals import ProposalProvenance  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402


def _container() -> dict:
    length, width, height, thickness = 3.0, 1.8, 1.8, 0.04
    return {
        "index": 41,
        "length": length,
        "width": width,
        "height": height,
        "thickness": thickness,
        "cut_x": 0.40,
        "cut_y": 0.40,
        "center": (0.0, 0.0, height / 2.0),
        "points": [
            [length / 2.0 - thickness, 0.0, 0.0],
            [-length / 2.0 + thickness, 0.0, 0.0],
            [0.0, width / 2.0 - thickness, 0.0],
            [0.0, -width / 2.0 + thickness, 0.0],
            [0.0, 0.0, height - thickness],
            [0.0, 0.0, thickness],
        ],
        "n_vecs": [
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
        ],
        "volume": length * width * height,
        "shelf": False,
        "is_prioritized": False,
        "packed_items": [],
    }


def _item(index: int, *, side: float = 0.20, length: float | None = None) -> ItemSpec:
    return ItemSpec(
        index=index,
        length=float(length if length is not None else side),
        width=side,
        height=side,
        mass=3.0,
    )


@dataclasses.dataclass(frozen=True)
class _Choice:
    item_index: int
    serial: int = 0
    position: tuple[float, float, float] | None = None
    pass_name: str = "normal"


class _TreeScanner:
    def __init__(self, mask: ExactMask, tree: dict[tuple[int, ...], tuple[_Choice, ...]]):
        self.mask = mask
        self.tree = tree
        self.calls: list[tuple[tuple[int, ...], tuple[int, ...], bool, bool, bool]] = []
        self.raise_prefixes: set[tuple[int, ...]] = set()
        self.expire_callback = None
        self.choice_selector = None

    def scan(
        self,
        state,
        pool,
        *,
        deadline=None,
        breadth_rescue=False,
        allow_deferred=True,
        allow_rescue=True,
    ):
        prefix = tuple(
            placed.item.index
            for container in state.containers
            for placed in container.placed
        )
        ordered = tuple(
            item.index if isinstance(item, ItemSpec) else int(item["index"])
            for item in pool
        )
        self.calls.append(
            (
                prefix,
                ordered,
                bool(breadth_rescue),
                bool(allow_deferred),
                bool(allow_rescue),
            )
        )
        if prefix in self.raise_prefixes:
            raise RuntimeError(f"synthetic branch failure: {prefix}")
        records: list[RootRecord] = []
        x_by_depth = (-1.05, -0.36, 0.34, 1.03)
        choices = self.tree.get(prefix, ())
        if self.choice_selector is not None:
            choices = self.choice_selector(state, pool, prefix, choices)
        for ordinal, choice in enumerate(choices):
            pool_index = ordered.index(choice.item_index)
            item = pool[pool_index]
            if not isinstance(item, ItemSpec):
                item = ItemSpec.from_dict(item)
            position = choice.position or (
                x_by_depth[min(len(prefix), len(x_by_depth) - 1)],
                0.52 - 0.30 * choice.serial,
                0.04 + 0.008 + item.height / 2.0,
            )
            proposal = PlacementProposal(
                item_index=item.index,
                pool_index=pool_index,
                container_index=0,
                orientation=0,
                position=position,
                source=f"tree-{item.index}-{choice.serial}",
            )
            root = self.mask.validate(state, pool, proposal, deadline=None)
            if root is None:
                raise AssertionError(f"synthetic proposal was not strict: {proposal}")
            records.append(
                RootRecord(
                    root,
                    ProposalProvenance((proposal.source,), ("floor",), (0.04,)),
                    choice.pass_name,
                    ordinal,
                )
            )
        counts = tuple(
            sum(record.pool_index == index for record in records)
            for index in range(len(pool))
        )
        catalog = RootCatalog(
            tuple(records),
            CatalogStats(
                accepted_roots=len(records),
                normal_roots=len(records),
                per_pool_raw=counts,
                per_pool_roots=counts,
                passes_completed=("normal",),
            ),
        )
        if self.expire_callback is not None and prefix:
            self.expire_callback()
        return catalog


class _SwitchClock:
    def __init__(self) -> None:
        self.base = time.perf_counter()
        self.expired = False

    def __call__(self) -> float:
        return self.base + (200.0 if self.expired else 0.0)


class DeterministicBeamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SearchSettings(front_floor_release_fill=0.0)
        self.mask = ExactMask(self.settings)
        self.state = build_packing_state([_container()])

    def _choose_b(self, items, tree, **kwargs):
        pool = tuple(items)
        scanner = _TreeScanner(self.mask, tree)
        catalog = scanner.scan(self.state, pool)
        planner = FutureSupportIngressBeam(
            scanner,
            self.mask,
            self.settings,
            clock=kwargs.pop("clock", None),
            **kwargs,
        )
        deadline = kwargs.pop("deadline", None) if kwargs else None
        if deadline is None:
            deadline = time.perf_counter() + 30.0
        return planner.choose_b(self.state, pool, catalog, deadline), scanner, catalog

    def test_locally_attractive_dead_end_loses_to_three_step_branch(self) -> None:
        a = _item(1, side=0.30)
        b, c, d = (_item(index) for index in range(2, 5))
        tree = {
            (): (_Choice(a.index), _Choice(b.index)),
            (a.index,): (),
            (b.index,): (_Choice(c.index),),
            (b.index, c.index): (_Choice(d.index),),
        }
        chosen, _, catalog = self._choose_b((a, b, c, d), tree)
        self.assertIs(chosen, next(root for root in catalog.roots if root.proposal.item_index == b.index))

    def test_proven_count_precedes_volume_and_volume_precedes_secondary(self) -> None:
        small = _item(10, side=0.16)
        continuation = _item(11, side=0.16)
        large = _item(12, side=0.42)
        tree = {
            (): (_Choice(small.index), _Choice(large.index)),
            (small.index,): (_Choice(continuation.index),),
            (large.index,): (),
        }
        chosen, _, catalog = self._choose_b((small, continuation, large), tree)
        self.assertIs(chosen, next(root for root in catalog.roots if root.proposal.item_index == small.index))

        medium = _item(20, side=0.24)
        bigger = _item(21, side=0.34)
        volume_tree = {(): (_Choice(medium.index), _Choice(bigger.index))}
        volume_chosen, _, volume_catalog = self._choose_b((medium, bigger), volume_tree)
        self.assertIs(
            volume_chosen,
            next(root for root in volume_catalog.roots if root.proposal.item_index == bigger.index),
        )

    def test_volume_precedence_is_not_lost_at_six_item_admission_cap(self) -> None:
        small = tuple(_item(220 + index, side=0.12) for index in range(6))
        large = _item(226, side=0.32)
        positions = (
            (-1.20, 0.55),
            (-0.80, 0.55),
            (-0.40, 0.55),
            (0.00, 0.55),
            (0.40, 0.55),
            (0.80, 0.55),
        )
        choices = tuple(
            _Choice(
                item.index,
                position=(x, y, 0.04 + 0.008 + item.height / 2.0),
            )
            for item, (x, y) in zip(small, positions)
        ) + (
            _Choice(
                large.index,
                serial=0,
                position=(0.0, 0.20, 0.04 + 0.008 + large.height / 2.0),
            ),
            _Choice(
                large.index,
                serial=1,
                position=(0.0, -0.20, 0.04 + 0.008 + large.height / 2.0),
            ),
        )
        chosen, _, catalog = self._choose_b((*small, large), {(): choices})
        self.assertEqual(chosen.proposal.item_index, large.index)
        self.assertTrue(any(chosen is root for root in catalog.roots))

    def test_future_coverage_precedes_clearance_at_two_root_cap(self) -> None:
        starter, continuation = _item(227, side=0.20), _item(228, side=0.16)
        z = 0.04 + 0.008 + starter.height / 2.0
        tree = {
            (): (
                _Choice(starter.index, position=(-0.20, 0.52, z)),
                _Choice(starter.index, position=(0.00, 0.52, z)),
                _Choice(starter.index, position=(0.90, 0.52, z)),
            )
        }
        scanner = _TreeScanner(self.mask, tree)

        def select_child(state, _pool, prefix, choices):
            if prefix == (starter.index,):
                last_x = float(state.containers[0].placed[-1].box.center[0])
                if last_x > 0.80:
                    return (_Choice(continuation.index),)
            return choices

        scanner.choice_selector = select_child
        pool = (starter, continuation)
        catalog = scanner.scan(self.state, pool)
        planner = FutureSupportIngressBeam(scanner, self.mask, self.settings)
        chosen = planner.choose_b(self.state, pool, catalog, time.perf_counter() + 30.0)
        self.assertIsNotNone(chosen)
        self.assertGreater(chosen.proposal.position[0], 0.80)

    def test_stale_roots_do_not_consume_per_item_root_cap(self) -> None:
        item = _item(229, side=0.18)
        tree = {
            (): (
                _Choice(item.index, serial=0),
                _Choice(item.index, serial=1),
                _Choice(item.index, serial=2),
            )
        }
        scanner = _TreeScanner(self.mask, tree)
        pool = (item,)
        catalog = scanner.scan(self.state, pool)
        stale_records = tuple(
            dataclasses.replace(
                record,
                root=dataclasses.replace(record.root, state_fingerprint="stale"),
            )
            if index > 0
            else record
            for index, record in enumerate(catalog.records)
        )
        stale_catalog = RootCatalog(stale_records, catalog.stats)
        planner = FutureSupportIngressBeam(scanner, self.mask, self.settings)
        chosen = planner.choose_b(
            self.state,
            pool,
            stale_catalog,
            time.perf_counter() + 30.0,
        )
        self.assertIs(chosen, catalog.roots[0])

    def test_stale_roots_do_not_distort_scarcity_before_six_item_cap(self) -> None:
        starters = tuple(_item(230 + index, side=0.12) for index in range(7))
        continuations = tuple(_item(240 + index, side=0.12) for index in range(7))
        tail = _item(247, side=0.12)
        tree = {
            (): (
                _Choice(starters[0].index, serial=0),
                _Choice(starters[0].index, serial=1),
                _Choice(starters[0].index, serial=2),
                *tuple(_Choice(item.index) for item in starters[1:]),
            ),
            **{
                (starter.index,): (_Choice(continuation.index),)
                for starter, continuation in zip(starters, continuations)
            },
            (starters[0].index, continuations[0].index): (_Choice(tail.index),),
        }
        scanner = _TreeScanner(self.mask, tree)
        pool = (*starters, *continuations, tail)
        catalog = scanner.scan(self.state, pool)
        item_zero_records = [
            record for record in catalog.records if record.item_index == starters[0].index
        ]
        stale_ids = {id(item_zero_records[1]), id(item_zero_records[2])}
        records = tuple(
            dataclasses.replace(
                record,
                root=dataclasses.replace(record.root, state_fingerprint="stale"),
            )
            if id(record) in stale_ids
            else record
            for record in catalog.records
        )
        stale_catalog = RootCatalog(records, catalog.stats)
        planner = FutureSupportIngressBeam(scanner, self.mask, self.settings)
        chosen = planner.choose_b(
            self.state,
            pool,
            stale_catalog,
            time.perf_counter() + 30.0,
        )
        self.assertEqual(chosen.proposal.item_index, starters[0].index)

    def test_stable_tie_order_and_twenty_identical_runs(self) -> None:
        first, second = _item(30), _item(31)
        tree = {(): (_Choice(first.index), _Choice(second.index))}
        scanner = _TreeScanner(self.mask, tree)
        pool = (first, second)
        catalog = scanner.scan(self.state, pool)
        planner = FutureSupportIngressBeam(scanner, self.mask, self.settings)
        results = [
            planner.choose_b(self.state, pool, catalog, time.perf_counter() + 30.0)
            for _ in range(20)
        ]
        self.assertTrue(all(result is results[0] for result in results))
        self.assertIs(results[0], catalog.roots[0])

    def test_scarcer_item_is_selected_before_secondary_geometry(self) -> None:
        common, rare = _item(40), _item(41)
        tree = {
            (): (
                _Choice(common.index, serial=0),
                _Choice(common.index, serial=1),
                _Choice(rare.index),
            )
        }
        chosen, _, catalog = self._choose_b((common, rare), tree)
        self.assertIs(chosen, next(root for root in catalog.roots if root.proposal.item_index == rare.index))

    def test_ingress_preserving_root_wins_for_same_item(self) -> None:
        placed, remaining = _item(50, side=0.30), _item(51, side=0.24)
        z = 0.04 + 0.008 + placed.height / 2.0
        tree = {
            (): (
                _Choice(placed.index, serial=0, position=(0.0, -0.48, z)),
                _Choice(placed.index, serial=1, position=(0.0, 0.52, z)),
            )
        }
        chosen, _, _ = self._choose_b((placed, remaining), tree)
        self.assertIsNotNone(chosen)
        self.assertGreater(chosen.proposal.position[1], 0.0)

    def test_deadline_returns_existing_depth_zero_incumbent(self) -> None:
        first, second = _item(60), _item(61)
        tree = {(): (_Choice(first.index), _Choice(second.index))}
        clock = _SwitchClock()
        scanner = _TreeScanner(self.mask, tree)
        pool = (first, second)
        catalog = scanner.scan(self.state, pool)
        scanner.expire_callback = lambda: setattr(clock, "expired", True)
        planner = FutureSupportIngressBeam(scanner, self.mask, self.settings, clock=clock)
        chosen = planner.choose_b(self.state, pool, catalog, clock.base + 100.0)
        self.assertIs(chosen, catalog.roots[0])

    def test_branch_exception_is_isolated(self) -> None:
        broken, viable, continuation = _item(70), _item(71), _item(72)
        tree = {
            (): (_Choice(broken.index), _Choice(viable.index)),
            (viable.index,): (_Choice(continuation.index),),
        }
        scanner = _TreeScanner(self.mask, tree)
        scanner.raise_prefixes.add((broken.index,))
        pool = (broken, viable, continuation)
        catalog = scanner.scan(self.state, pool)
        planner = FutureSupportIngressBeam(scanner, self.mask, self.settings)
        chosen = planner.choose_b(self.state, pool, catalog, time.perf_counter() + 30.0)
        self.assertIs(chosen, next(root for root in catalog.roots if root.proposal.item_index == viable.index))

    def test_b_considers_pool_position_39_and_child_scans_are_normal_only(self) -> None:
        items = tuple(_item(100 + index, side=0.12) for index in range(40))
        tree = {(): (_Choice(items[39].index),)}
        chosen, scanner, catalog = self._choose_b(items, tree)
        self.assertIs(chosen, catalog.roots[0])
        self.assertEqual(chosen.proposal.pool_index, 39)
        self.assertTrue(any(len(ordered) == 39 for _, ordered, _, _, _ in scanner.calls))
        child_calls = [call for call in scanner.calls if call[0]]
        self.assertTrue(child_calls)
        self.assertTrue(
            all(not breadth and not deferred and not rescue for _, _, breadth, deferred, rescue in child_calls)
        )

    def test_b_never_expands_deferred_child_catalog_records(self) -> None:
        starter, deferred, tail = _item(150), _item(151), _item(152)
        tree = {
            (): (_Choice(starter.index),),
            (starter.index,): (_Choice(deferred.index, pass_name="deferred"),),
            (starter.index, deferred.index): (_Choice(tail.index),),
        }
        _, scanner, _ = self._choose_b((starter, deferred, tail), tree)
        self.assertFalse(
            any(
                prefix == (starter.index, deferred.index)
                for prefix, _, _, _, _ in scanner.calls
            )
        )

    def test_normal_zero_child_does_not_starve_later_sibling_scan(self) -> None:
        first, second = _item(160), _item(161)
        scanner = _TreeScanner(
            self.mask,
            {(): (_Choice(first.index), _Choice(second.index))},
        )
        pool = (first, second)
        catalog = scanner.scan(self.state, pool)
        planner = FutureSupportIngressBeam(scanner, self.mask, self.settings)
        chosen = planner.choose_b(
            self.state,
            pool,
            catalog,
            time.perf_counter() + 30.0,
        )
        self.assertIsNotNone(chosen)
        child_calls = [call for call in scanner.calls if call[0]]
        self.assertEqual({call[0] for call in child_calls}, {(first.index,), (second.index,)})
        self.assertTrue(
            all(not deferred and not rescue for _, _, _, deferred, rescue in child_calls)
        )

    def test_choose_c_never_scans_children_and_returns_catalog_identity(self) -> None:
        item = _item(200)
        scanner = _TreeScanner(self.mask, {(): (_Choice(item.index),)})
        pool = (item,)
        catalog = scanner.scan(self.state, pool)
        scanner.raise_prefixes.add((item.index,))
        before_calls = len(scanner.calls)
        planner = FutureSupportIngressBeam(scanner, self.mask, self.settings)
        chosen = planner.choose_c(self.state, pool, catalog, time.perf_counter() + 30.0)
        self.assertIs(chosen, catalog.roots[0])
        self.assertEqual(len(scanner.calls), before_calls)

    def test_real_catalog_integration_returns_original_strict_root(self) -> None:
        item = _item(210)
        pool = (item,)
        scanner = StrictRootScanner(
            self.settings,
            mask=self.mask,
            per_pool_cap=2,
            global_cap=2,
            first_pass_raw_cap=16,
        )
        catalog = scanner.scan(self.state, pool, deadline=time.perf_counter() + 5.0)
        self.assertTrue(catalog.roots)
        planner = FutureSupportIngressBeam(scanner, self.mask, self.settings)
        chosen = planner.choose_c(self.state, pool, catalog, time.perf_counter() + 5.0)
        self.assertTrue(any(chosen is root for root in catalog.roots))
        self.assertIsInstance(chosen, ValidatedRoot)

    def test_node_is_immutable_and_module_has_no_forbidden_search_or_action_path(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(BeamNode))
        module = sys.modules[FutureSupportIngressBeam.__module__]
        source = inspect.getsource(module)
        lowered = source.lower()
        self.assertNotIn("_issue_validated_root", source)
        self.assertNotIn("placementproposal", lowered)
        self.assertNotIn("highscore", lowered)
        self.assertNotIn("mcts", lowered)
        self.assertNotIn("from .ems", lowered)
        self.assertNotIn("import ems", lowered)
        self.assertNotIn("random", lowered)
        self.assertNotIn('"place_pos"', source)


if __name__ == "__main__":
    unittest.main()
