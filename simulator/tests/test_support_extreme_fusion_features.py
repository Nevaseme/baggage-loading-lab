from __future__ import annotations

import dataclasses
import inspect
import math
import pathlib
import sys
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    RootCatalog,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.features import (  # noqa: E402
    FutureFeatures,
    compute_future_features,
)
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    AABB,
    ItemSpec,
    PlacedItem,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.transition import SimState  # noqa: E402


def _container_dict(*, shelf: bool = False, packed: list[dict] | None = None) -> dict:
    length, width, height, thickness = 2.0, 1.5, 1.6, 0.04
    return {
        "index": 17,
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
        "shelf": shelf,
        "is_prioritized": False,
        "packed_items": packed or [],
    }


def _item(
    index: int,
    *,
    length: float = 0.24,
    width: float = 0.20,
    height: float = 0.16,
    mass: float = 4.0,
    prioritized: bool = False,
    soft: bool = False,
) -> ItemSpec:
    return ItemSpec(
        index=index,
        length=length,
        width=width,
        height=height,
        mass=mass,
        is_prioritized=prioritized,
        is_soft=soft,
    )


def _sim(
    *,
    packed: list[dict] | None = None,
    pool: tuple[ItemSpec, ...] = (),
    shelf: bool = False,
) -> SimState:
    state = build_packing_state([_container_dict(shelf=shelf, packed=packed)])
    return SimState.from_current(state, pool)


class FutureFeatureTests(unittest.TestCase):
    def test_empty_and_zero_mass_features_are_finite_and_bounded(self) -> None:
        sim = _sim(pool=(_item(1, mass=0.0),))
        features = compute_future_features(sim)
        self.assertIsInstance(features, FutureFeatures)
        for name, value in dataclasses.asdict(features).items():
            self.assertTrue(math.isfinite(float(value)), name)
            self.assertGreaterEqual(float(value), 0.0, name)
            self.assertLessEqual(float(value), 1.0, name)

    def test_support_footprint_subtraction_reduces_capacity(self) -> None:
        item = _item(1, length=0.35, width=0.30, height=0.16)
        free = compute_future_features(_sim(pool=(item,)))
        blocker = {
            "index": 99,
            "length": 0.80,
            "width": 0.70,
            "height": 0.16,
            "pos": (0.0, 0.20, 0.128),
            "orn": (0.0, 0.0, 0.0, 1.0),
        }
        blocked = compute_future_features(_sim(pool=(item,), packed=[blocker]))
        self.assertLess(blocked.compatible_support_capacity, free.compatible_support_capacity)
        self.assertLess(blocked.largest_free_support, free.largest_free_support)

    def test_shelf_layer_uses_the_official_22mm_drop_gap_for_subtraction(self) -> None:
        tiny = _item(1, length=0.10, width=0.10, height=0.01)
        shelf_top = 0.84
        blocker = {
            "index": 98,
            "length": 0.30,
            "width": 0.30,
            "height": 0.16,
            "pos": (0.0, 0.30, shelf_top + 0.022 + 0.08),
            "orn": (0.0, 0.0, 0.0, 1.0),
        }
        floating = dict(blocker, pos=(0.0, 0.30, shelf_top + 0.050 + 0.08))
        resting = _sim(pool=(tiny,), packed=[blocker], shelf=True)
        airborne = _sim(pool=(tiny,), packed=[floating], shelf=True)
        module = sys.modules[compute_future_features.__module__]

        def shelf_free_area(sim: SimState) -> float:
            total = 0.0
            for surface in module._support_surfaces(sim.packing.containers, SearchSettings()):
                if not math.isclose(surface.height, shelf_top, abs_tol=1e-9):
                    continue
                xs, ys, free, _ = module._surface_grid(surface)
                total += sum(
                    (xs[column + 1] - xs[column]) * (ys[row + 1] - ys[row])
                    for row in range(len(ys) - 1)
                    for column in range(len(xs) - 1)
                    if free[row][column]
                )
            return total

        self.assertLess(shelf_free_area(resting), shelf_free_area(airborne))

    def test_priority_soft_and_combined_protection_capacity(self) -> None:
        cases = (
            (True, False, _item(1), _item(2, prioritized=True)),
            (False, True, _item(3), _item(4, soft=True)),
            (True, True, _item(5, prioritized=True), _item(6, prioritized=True, soft=True)),
        )
        for lower_priority, lower_soft, incompatible, compatible in cases:
            with self.subTest(priority=lower_priority, soft=lower_soft):
                lower = {
                    "index": 90,
                    "length": 0.40,
                    "width": 0.40,
                    "height": 0.20,
                    "is_prioritized": lower_priority,
                    "is_soft": lower_soft,
                    "pos": (0.0, 0.30, 0.148),
                    "orn": (0.0, 0.0, 0.0, 1.0),
                }
                incompatible_features = compute_future_features(
                    _sim(pool=(incompatible,), packed=[lower])
                )
                compatible_features = compute_future_features(
                    _sim(pool=(compatible,), packed=[lower])
                )
                self.assertLess(
                    incompatible_features.protection_compatible_capacity,
                    compatible_features.protection_compatible_capacity,
                )

    def test_front_ingress_blocker_lowers_access(self) -> None:
        item = _item(1)
        clear = compute_future_features(_sim(pool=(item,)))
        blocker = {
            "index": 91,
            "length": 1.60,
            "width": 0.35,
            "height": 0.40,
            "pos": (0.0, -0.48, 0.24),
            "orn": (0.0, 0.0, 0.0, 1.0),
        }
        blocked = compute_future_features(_sim(pool=(item,), packed=[blocker]))
        self.assertLess(blocked.ingress_access, clear.ingress_access)

    def test_ingress_span_and_height_come_from_one_real_orientation(self) -> None:
        blockers = [
            {
                "index": 91,
                "length": 0.20,
                "width": 0.35,
                "height": 0.10,
                "pos": (0.0, -0.48, 0.15),
                "orn": (0.0, 0.0, 0.0, 1.0),
            },
            {
                "index": 92,
                "length": 0.20,
                "width": 0.35,
                "height": 0.10,
                "pos": (0.60, -0.48, 0.35),
                "orn": (0.0, 0.0, 0.0, 1.0),
            },
        ]
        independently_tiny = _item(1, length=0.10, width=0.10, height=0.10)
        anisotropic = _item(2, length=1.00, width=0.10, height=0.50)
        tiny_access = compute_future_features(
            _sim(pool=(independently_tiny,), packed=blockers)
        ).ingress_access
        anisotropic_access = compute_future_features(
            _sim(pool=(anisotropic,), packed=blockers)
        ).ingress_access
        self.assertLess(anisotropic_access, tiny_access)

    def test_sliver_area_increases_when_only_tiny_gap_remains(self) -> None:
        item = _item(1, length=0.25, width=0.25)
        clear = compute_future_features(_sim(pool=(item,)))
        blockers = [
            {
                "index": 90,
                "length": 0.85,
                "width": 1.30,
                "height": 0.16,
                "pos": (-0.52, 0.30, 0.128),
                "orn": (0.0, 0.0, 0.0, 1.0),
            },
            {
                "index": 91,
                "length": 0.85,
                "width": 1.30,
                "height": 0.16,
                "pos": (0.52, 0.30, 0.128),
                "orn": (0.0, 0.0, 0.0, 1.0),
            },
        ]
        sliver = compute_future_features(_sim(pool=(item,), packed=blockers))
        self.assertGreater(sliver.sliver_area, clear.sliver_area)

    def test_artificial_subtraction_boundaries_do_not_hide_a_wide_free_strip(self) -> None:
        item = _item(1, length=1.57, width=0.50, height=0.10)
        blocker = {
            "index": 90,
            "length": 0.40,
            "width": 0.70,
            "height": 0.16,
            "pos": (0.0, 0.35, 0.128),
            "orn": (0.0, 0.0, 0.0, 1.0),
        }
        features = compute_future_features(_sim(pool=(item,), packed=[blocker]))
        self.assertGreater(features.compatible_support_capacity, 0.0)
        self.assertGreater(features.largest_free_support, 0.40)

    def test_largest_free_support_ignores_larger_slender_nonfitting_region(self) -> None:
        item = _item(1, length=0.50, width=0.50, height=0.50)
        sim = _sim(pool=(item,))
        container = sim.packing.containers[0]
        blocker_item = _item(90)
        container.placed.extend(
            [
                PlacedItem(
                    blocker_item,
                    AABB(
                        np.array((-0.56, -0.71, 0.048)),
                        np.array((0.46, 0.71, 0.20)),
                        axis_aligned=False,
                    ),
                ),
                PlacedItem(
                    blocker_item,
                    AABB(
                        np.array((0.46, -0.21, 0.048)),
                        np.array((0.96, 0.71, 0.20)),
                        axis_aligned=False,
                    ),
                ),
            ]
        )
        features = compute_future_features(sim)
        floor_area = 1.92 * 1.42
        self.assertAlmostEqual(features.largest_free_support, 0.25 / floor_area, places=6)

    def test_overhead_obstacle_removes_collision_invalid_support_capacity(self) -> None:
        item = _item(1, length=0.50, width=0.50, height=0.50)
        sim = _sim(pool=(item,))
        container = sim.packing.containers[0]
        container.static_obstacles.clear()
        container.placed.append(
            PlacedItem(
                _item(90),
                AABB(
                    np.array((-0.96, -0.71, 0.50)),
                    np.array((0.96, 0.71, 0.60)),
                    axis_aligned=False,
                ),
            )
        )
        features = compute_future_features(sim)
        self.assertEqual(features.compatible_support_capacity, 0.0)

    def test_inner_roof_thickness_is_not_counted_as_vertical_capacity(self) -> None:
        raw = _container_dict()
        raw.update(
            {
                "length": 0.50,
                "width": 0.50,
                "volume": 0.50 * 0.50 * 1.60,
                "points": [
                    [0.21, 0.0, 0.0],
                    [-0.21, 0.0, 0.0],
                    [0.0, 0.21, 0.0],
                    [0.0, -0.21, 0.0],
                    [0.0, 0.0, 1.56],
                    [0.0, 0.0, 0.04],
                ],
            }
        )
        item = _item(1, length=0.40, width=0.40, height=1.53)
        sim = SimState.from_current(build_packing_state([raw]), (item,))
        features = compute_future_features(sim)
        self.assertEqual(features.compatible_support_capacity, 0.0)

    def test_floor_8mm_bottom_offset_is_deducted_from_vertical_headroom(self) -> None:
        raw = _container_dict()
        raw.update(
            {
                "length": 0.50,
                "width": 0.50,
                "volume": 0.50 * 0.50 * 1.60,
                "points": [
                    [0.21, 0.0, 0.0],
                    [-0.21, 0.0, 0.0],
                    [0.0, 0.21, 0.0],
                    [0.0, -0.21, 0.0],
                    [0.0, 0.0, 1.56],
                    [0.0, 0.0, 0.04],
                ],
            }
        )
        # Fits if measured from the physical floor plane (1.520 m), but not
        # from the validator-compatible bottom at floor + 8 mm (1.512 m).
        item = _item(1, length=0.40, width=0.40, height=1.516)
        sim = SimState.from_current(build_packing_state([raw]), (item,))
        sim.packing.containers[0].static_obstacles.clear()
        self.assertEqual(compute_future_features(sim).compatible_support_capacity, 0.0)

    def test_heavy_high_center_of_gravity_is_worse(self) -> None:
        low = {
            "index": 80,
            "length": 0.30,
            "width": 0.30,
            "height": 0.20,
            "mass": 10.0,
            "pos": (0.0, 0.30, 0.14),
            "orn": (0.0, 0.0, 0.0, 1.0),
        }
        high = dict(low, pos=(0.0, 0.30, 0.90))
        low_features = compute_future_features(_sim(pool=(_item(1),), packed=[low]))
        high_features = compute_future_features(_sim(pool=(_item(1),), packed=[high]))
        self.assertGreater(low_features.low_mass_cog_goodness, high_features.low_mass_cog_goodness)

    def test_weak_support_and_clearance_have_lower_margins(self) -> None:
        settings = SearchSettings()
        state = build_packing_state([_container_dict()])
        item = _item(1)
        pool = (item,)
        mask = ExactMask(settings)
        proposal = __import__(
            "agents.support_extreme_fusion_beam_exact_mask.model",
            fromlist=["PlacementProposal"],
        ).PlacementProposal(1, 0, 0, 0, (0.0, 0.30, 0.128), "fixture")
        root = mask.validate(state, pool, proposal)
        self.assertIsNotNone(root)
        strong = compute_future_features(SimState.from_current(state, pool), selected_root=root)
        weak_root = dataclasses.replace(root, support_ratio=0.70, min_clearance=0.001)
        weak = compute_future_features(SimState.from_current(state, pool), selected_root=weak_root)
        self.assertGreater(strong.min_support_margin, weak.min_support_margin)
        self.assertGreater(strong.min_clearance_margin, weak.min_clearance_margin)

    def test_tilted_top_is_not_counted_as_support(self) -> None:
        item = _item(1)
        aligned_packed = {
            "index": 90,
            "length": 0.40,
            "width": 0.40,
            "height": 0.20,
            "pos": (0.0, 0.30, 0.148),
            "orn": (0.0, 0.0, 0.0, 1.0),
        }
        tilted_packed = dict(
            aligned_packed,
            orn=(0.25, 0.0, 0.0, 0.9682458),
        )
        aligned = compute_future_features(_sim(pool=(item,), packed=[aligned_packed]))
        tilted = compute_future_features(_sim(pool=(item,), packed=[tilted_packed]))
        self.assertGreater(
            aligned.compatible_support_capacity,
            tilted.compatible_support_capacity,
        )

    def test_strict_catalog_features_are_deterministic_and_parent_unchanged(self) -> None:
        settings = SearchSettings()
        item = _item(1)
        state = build_packing_state([_container_dict()])
        sim = SimState.from_current(state, (item,))
        before = sim.fingerprint(settings)
        scanner = StrictRootScanner(settings, per_pool_cap=4, global_cap=8, first_pass_raw_cap=16)
        catalog = scanner.scan(state, (item,))
        first = compute_future_features(sim, catalog=catalog, settings=settings)
        second = compute_future_features(sim, catalog=catalog, settings=settings)
        self.assertEqual(first, second)
        self.assertEqual(before, sim.fingerprint(settings))
        self.assertGreaterEqual(first.future_covered_items, 0.0)
        self.assertLessEqual(first.future_covered_items, 1.0)

    def test_catalog_coverage_volume_and_rarity_use_pool_occurrences(self) -> None:
        settings = SearchSettings()
        small = _item(7, length=0.20, width=0.20, height=0.10)
        large = _item(7, length=0.40, width=0.30, height=0.20)
        sim = _sim(pool=(small, large))
        scanner = StrictRootScanner(settings, per_pool_cap=8, global_cap=16, first_pass_raw_cap=32)
        full = scanner.scan(sim.packing, sim.pool)
        self.assertTrue(full.records)
        selected_record = full.records[0]
        one = RootCatalog((selected_record,), full.stats)
        features = compute_future_features(sim, catalog=one, settings=settings)
        selected = sim.pool[selected_record.pool_index]
        self.assertAlmostEqual(features.future_covered_items, 0.5)
        self.assertAlmostEqual(
            features.future_covered_volume,
            selected.volume / (small.volume + large.volume),
        )
        many_same_occurrence = RootCatalog(
            tuple(record for record in full.records if record.pool_index == selected_record.pool_index),
            full.stats,
        )
        many = compute_future_features(sim, catalog=many_same_occurrence, settings=settings)
        self.assertGreater(features.root_scarcity, many.root_scarcity)

    def test_root_scarcity_and_robustness_include_rootless_occurrences(self) -> None:
        settings = SearchSettings()
        first = _item(1)
        second = _item(2)
        sim = _sim(pool=(first, second))
        full = StrictRootScanner(
            settings, per_pool_cap=4, global_cap=8, first_pass_raw_cap=32
        ).scan(sim.packing, sim.pool)
        roots0 = tuple(record for record in full.records if record.pool_index == 0)
        self.assertGreaterEqual(len(roots0), 2)
        zero = compute_future_features(
            sim, catalog=RootCatalog.empty(len(sim.pool)), settings=settings
        )
        singleton = compute_future_features(
            sim, catalog=RootCatalog((roots0[0],), full.stats), settings=settings
        )
        multi = compute_future_features(
            sim, catalog=RootCatalog(roots0, full.stats), settings=settings
        )
        self.assertAlmostEqual(zero.root_scarcity, 1.0)
        self.assertAlmostEqual(singleton.root_scarcity, 0.75)
        self.assertLess(multi.root_scarcity, singleton.root_scarcity)

        required = settings.rigid_support_ratio
        margins = [
            min(
                max(0.0, min(1.0, (record.root.support_ratio - required) / (1.0 - required))),
                max(0.0, min(1.0, record.root.min_clearance / settings.path_clearance)),
            )
            for record in roots0
        ]
        self.assertAlmostEqual(multi.root_robustness, max(margins) / 2.0)

    def test_stale_or_foreign_profile_catalog_roots_do_not_count_as_coverage(self) -> None:
        settings = SearchSettings()
        item = _item(1)
        original = _sim(pool=(item,))
        catalog = StrictRootScanner(
            settings, per_pool_cap=2, global_cap=2, first_pass_raw_cap=16
        ).scan(original.packing, original.pool)
        self.assertTrue(catalog.records)
        blocker = {
            "index": 99,
            "length": 0.30,
            "width": 0.30,
            "height": 0.16,
            "pos": (0.0, 0.20, 0.128),
            "orn": (0.0, 0.0, 0.0, 1.0),
        }
        changed = _sim(pool=(item,), packed=[blocker])
        stale = compute_future_features(changed, catalog=catalog, settings=settings)
        foreign_profile = compute_future_features(
            original,
            catalog=catalog,
            settings=dataclasses.replace(settings, path_clearance=0.02),
        )
        self.assertEqual(stale.future_covered_items, 0.0)
        self.assertEqual(foreign_profile.future_covered_items, 0.0)

    def test_stale_or_foreign_profile_selected_root_has_zero_margins(self) -> None:
        settings = SearchSettings()
        item = _item(1)
        original = _sim(pool=(item,))
        root = StrictRootScanner(
            settings, per_pool_cap=1, global_cap=1, first_pass_raw_cap=16
        ).scan(original.packing, original.pool).roots[0]
        blocker = {
            "index": 99,
            "length": 0.30,
            "width": 0.30,
            "height": 0.16,
            "pos": (0.0, 0.20, 0.128),
            "orn": (0.0, 0.0, 0.0, 1.0),
        }
        changed = compute_future_features(
            _sim(pool=(item,), packed=[blocker]),
            selected_root=root,
            settings=settings,
        )
        foreign_profile = compute_future_features(
            original,
            selected_root=root,
            settings=dataclasses.replace(settings, path_clearance=0.02),
        )
        self.assertEqual(changed.min_support_margin, 0.0)
        self.assertEqual(changed.min_clearance_margin, 0.0)
        self.assertEqual(foreign_profile.min_support_margin, 0.0)
        self.assertEqual(foreign_profile.min_clearance_margin, 0.0)

    def test_invalid_selected_root_never_falls_back_to_valid_catalog_margins(self) -> None:
        settings = SearchSettings()
        item = _item(1)
        sim = _sim(pool=(item,))
        catalog = StrictRootScanner(
            settings, per_pool_cap=2, global_cap=2, first_pass_raw_cap=16
        ).scan(sim.packing, sim.pool)
        self.assertTrue(catalog.roots)
        catalog_only = compute_future_features(sim, catalog=catalog, settings=settings)
        self.assertGreater(catalog_only.min_support_margin, 0.0)
        invalid_selected = dataclasses.replace(
            catalog.roots[0], state_fingerprint="foreign-state"
        )
        selected = compute_future_features(
            sim,
            catalog=catalog,
            selected_root=invalid_selected,
            settings=settings,
        )
        self.assertEqual(selected.min_support_margin, 0.0)
        self.assertEqual(selected.min_clearance_margin, 0.0)

    def test_all_named_features_have_documented_goodness_or_penalty_bounds(self) -> None:
        names = set(FutureFeatures.__dataclass_fields__)
        self.assertTrue(
            {
                "future_covered_items",
                "future_covered_volume",
                "root_robustness",
                "root_scarcity",
                "compatible_support_capacity",
                "protection_compatible_capacity",
                "largest_free_support",
                "ingress_access",
                "fragmentation",
                "sliver_area",
                "low_mass_cog_goodness",
                "min_support_margin",
                "min_clearance_margin",
                "low_stack",
            }.issubset(names)
        )

    def test_feature_module_does_not_issue_receipts_or_import_search_engines(self) -> None:
        module = sys.modules[compute_future_features.__module__]
        source = inspect.getsource(module)
        self.assertNotIn("_issue_validated_root", source)
        self.assertNotIn("StrictRootScanner", source)
        self.assertNotIn("ExactMask", source)
        self.assertNotIn("highscore", source)
        lowered = source.lower()
        self.assertNotIn("from .mcts", lowered)
        self.assertNotIn("import mcts", lowered)
        self.assertNotIn("from .ems", lowered)
        self.assertNotIn("import ems", lowered)


if __name__ == "__main__":
    unittest.main()
