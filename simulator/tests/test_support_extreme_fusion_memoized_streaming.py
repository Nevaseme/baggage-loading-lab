from __future__ import annotations

import copy
import dataclasses
from decimal import Decimal
import pathlib
import pickle
import sys
import time
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.layered_proxy import (  # noqa: E402
    CheckedProxyTransition,
    LayeredProxy,
    LayeredProxyState,
    ProxyTopologyCache,
    ProxyWork,
    ProxyWorkQuota,
)
from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    CatalogStats,
    RootCatalog,
    RootRecord,
)
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.maxrects_regret import (  # noqa: E402
    MemoizedStreamingRegretProxySelector,
    RegretProxySelector,
)
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    ItemSpec,
    PlacementProposal,
    ValidatedRoot,
)
from agents.support_extreme_fusion_beam_exact_mask.proposals import (  # noqa: E402
    ProposalProvenance,
    ProposalSource,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import (  # noqa: E402
    SearchSettings,
)
from agents.support_extreme_fusion_beam_exact_mask.state import (  # noqa: E402
    build_packing_state,
)
from agents.support_extreme_fusion_beam_exact_mask.transition import (  # noqa: E402
    SimState,
)


def _container() -> dict:
    length, width, height, thickness = 2.0, 1.5, 1.6, 0.04
    return {
        "index": 0,
        "length": length,
        "width": width,
        "height": height,
        "thickness": thickness,
        "cut_x": 0.4,
        "cut_y": 0.4,
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


def _item(index: int, *, side: float = 0.20) -> dict:
    return {
        "index": index,
        "length": side,
        "width": side * 0.8,
        "height": side * 0.6,
        "mass": 2.0,
        "is_prioritized": False,
        "is_soft": False,
    }


def _state(pool_size: int = 2):
    pool = tuple(_item(10 + index) for index in range(pool_size))
    sim = SimState.from_current(build_packing_state([_container()]), pool)
    proxy = LayeredProxy()
    return proxy, proxy.from_sim_state(sim)


def _selector_case(pool_size: int = 3, roots: int = 1):
    settings = SearchSettings()
    mask = ExactMask(settings)
    state = build_packing_state([_container()])
    pool = tuple(ItemSpec.from_dict(_item(30 + index)) for index in range(pool_size))
    records = []
    for ordinal in range(roots):
        pool_index = ordinal % pool_size
        item = pool[pool_index]
        proposal = PlacementProposal(
            item_index=item.index,
            pool_index=pool_index,
            container_index=0,
            orientation=0,
            position=(-0.70 + 0.30 * ordinal, 0.45, 0.048 + item.height / 2.0),
            source=ProposalSource.FREE_RECTANGLE_BOUNDARY.value,
        )
        root = mask.validate(
            state, pool, proposal, deadline=time.perf_counter() + 10.0
        )
        if root is None:
            raise AssertionError(f"invalid selector fixture root: {proposal}")
        records.append(
            RootRecord(
                root,
                ProposalProvenance((proposal.source,), ("floor",), (0.04,)),
                "normal",
                ordinal,
            )
        )
    catalog = RootCatalog(
        tuple(records),
        CatalogStats(
            accepted_roots=len(records),
            normal_roots=len(records),
            per_pool_roots=tuple(
                sum(record.pool_index == index for record in records)
                for index in range(pool_size)
            ),
        ),
    )
    return settings, mask, SimState.from_current(state, pool), catalog


class _CountingProxy(LayeredProxy):
    def __init__(self):
        super().__init__()
        self.check_calls = 0
        self.metric_calls = 0

    def _check(self, *args, **kwargs):
        self.check_calls += 1
        return super()._check(*args, **kwargs)

    def metrics(self, *args, **kwargs):
        self.metric_calls += 1
        return super().metrics(*args, **kwargs)


class MemoizedLayeredProxyTests(unittest.TestCase):
    def _fresh_checked_transition(self):
        proxy, state = _state()
        cache = ProxyTopologyCache()
        transition = proxy.preview_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            ProxyWorkQuota(max_fit_tests=1, max_candidates=1),
            proxy.metrics(state),
            cache,
        ).transitions[0]
        return proxy, state, cache, transition

    def test_preview_candidates_preserve_legacy_candidate_tuple_exactly(self):
        proxy, state = _state()
        quota = ProxyWorkQuota(max_fit_tests=128, max_candidates=128)
        legacy = proxy.enumerate_candidates(
            state, state.remaining[0].key, ProxyWork(), quota
        )
        before = proxy.metrics(state)
        previews = proxy.preview_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            quota,
            before,
            ProxyTopologyCache(),
        )

        preview_candidates = tuple(
            transition.candidate for transition in previews.transitions
        )
        self.assertEqual(len(preview_candidates), len(legacy.candidates))
        self.assertTrue(
            all(
                proxy._same_candidate(preview, expected)
                for preview, expected in zip(preview_candidates, legacy.candidates)
            )
        )
        self.assertEqual(previews.work, legacy.work)
        self.assertEqual(previews.attempted_fit_tests, legacy.attempted_fit_tests)

    def test_preview_matches_legacy_child_metrics_waste_and_local_cost(self):
        proxy, state = _state()
        quota = ProxyWorkQuota(max_fit_tests=64, max_candidates=64)
        before = proxy.metrics(state)
        previews = proxy.preview_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            quota,
            before,
            ProxyTopologyCache(),
        )
        transition = previews.transitions[0]
        legacy_child = proxy.apply(state, transition.candidate)
        legacy_metrics = proxy.metrics(legacy_child)
        selector = object.__new__(RegretProxySelector)
        selector.protection_materiality = 0.01
        legacy_cost = selector._local_cost(
            state, before, legacy_metrics, transition.candidate
        )

        self.assertEqual(transition.child_state.fingerprint, legacy_child.fingerprint)
        self.assertEqual(transition.child_metrics, legacy_metrics)
        self.assertEqual(
            transition.maxrect_waste,
            selector._maxrect_waste(
                state.containers[transition.candidate.container_ordinal],
                transition.candidate,
            ),
        )
        self.assertEqual(selector._checked_local_cost(transition), legacy_cost)

    def test_one_preview_check_and_metric_are_not_repeated_by_commit(self):
        pool = tuple(_item(20 + index) for index in range(2))
        sim = SimState.from_current(build_packing_state([_container()]), pool)
        proxy = _CountingProxy()
        state = proxy.from_sim_state(sim)
        before = LayeredProxy.metrics(proxy, state)
        proxy.check_calls = 0
        proxy.metric_calls = 0
        cache = ProxyTopologyCache()
        previews = proxy.preview_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            ProxyWorkQuota(max_fit_tests=1, max_candidates=1),
            before,
            cache,
        )
        self.assertEqual(len(previews.transitions), 1)
        self.assertEqual(proxy.check_calls, 1)
        self.assertEqual(proxy.metric_calls, 1)

        transition = previews.transitions[0]
        committed_state, committed_metrics = proxy.commit_transition(
            state, transition, cache
        )
        self.assertEqual(proxy.check_calls, 1)
        self.assertEqual(proxy.metric_calls, 1)
        self.assertIs(committed_state, transition.child_state)
        self.assertIs(committed_metrics, transition.child_metrics)

    def test_foreign_stale_or_altered_transition_fails_closed(self):
        proxy, state = _state()
        before = proxy.metrics(state)
        cache = ProxyTopologyCache()
        transition = proxy.preview_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            ProxyWorkQuota(max_fit_tests=1, max_candidates=1),
            before,
            cache,
        ).transitions[0]
        _other_proxy, other = _state(3)

        with self.assertRaises(ValueError):
            proxy.commit_transition(other, transition, cache)
        with self.assertRaises(ValueError):
            proxy.commit_transition(state, transition, ProxyTopologyCache())
        with self.assertRaises(ValueError):
            proxy.commit_transition(
                state,
                dataclasses.replace(
                    transition,
                    maxrect_waste=(1.0, 1.0, 1.0),
                ),
                cache,
            )

        object.__setattr__(
            transition.child_state,
            "remaining",
            state.remaining,
        )
        with self.assertRaises(ValueError):
            proxy.commit_transition(state, transition, cache)

    def test_commit_digest_covers_every_nested_support_box_item_and_remaining_field(self):
        def support_container_ordinal(transition):
            patch = transition.child_state.containers[0].supports[-1]
            object.__setattr__(patch, "container_ordinal", patch.container_ordinal + 1)

        def box_axis_alignment(transition):
            box = transition.child_state.containers[0].boxes[-1].box
            object.__setattr__(box, "axis_aligned", not box.axis_aligned)

        def replace_box_item(transition, **changes):
            box = transition.child_state.containers[0].boxes[-1]
            object.__setattr__(box, "item", dataclasses.replace(box.item, **changes))

        def replace_remaining_item(transition, **changes):
            occurrence = transition.child_state.remaining[0]
            object.__setattr__(
                occurrence,
                "item",
                dataclasses.replace(occurrence.item, **changes),
            )

        mutations = {
            "support.container_ordinal": support_container_ordinal,
            "box.aabb.axis_aligned": box_axis_alignment,
            "box.item.index": lambda value: replace_box_item(value, index=901),
            "box.item.dimensions": lambda value: replace_box_item(
                value, length=value.child_state.containers[0].boxes[-1].item.length + 0.01
            ),
            "box.item.mass": lambda value: replace_box_item(value, mass=9.0),
            "box.item.priority": lambda value: replace_box_item(
                value, is_prioritized=True
            ),
            "box.item.soft": lambda value: replace_box_item(value, is_soft=True),
            "box.item.belongs_to": lambda value: replace_box_item(value, belongs_to=0),
            "box.item.pos": lambda value: replace_box_item(
                value, pos=(0.1, 0.2, 0.3)
            ),
            "box.item.orn": lambda value: replace_box_item(
                value, orn=(0.0, 0.0, 0.0, 1.0)
            ),
            "box.item.presence": lambda value: object.__setattr__(
                value.child_state.containers[0].boxes[-1], "item", None
            ),
            "box.tag.presence": lambda value: object.__setattr__(
                value.child_state.containers[0].boxes[-1], "tag", None
            ),
            "box.occurrence.presence": lambda value: object.__setattr__(
                value.child_state.containers[0].boxes[-1], "occurrence", None
            ),
            "remaining.item.index": lambda value: replace_remaining_item(
                value, index=902
            ),
            "remaining.item.dimensions": lambda value: replace_remaining_item(
                value, width=value.child_state.remaining[0].item.width + 0.01
            ),
            "remaining.item.mass": lambda value: replace_remaining_item(
                value, mass=8.0
            ),
            "remaining.item.priority": lambda value: replace_remaining_item(
                value, is_prioritized=True
            ),
            "remaining.item.soft": lambda value: replace_remaining_item(
                value, is_soft=True
            ),
            "remaining.item.belongs_to": lambda value: replace_remaining_item(
                value, belongs_to=0
            ),
            "remaining.item.pos": lambda value: replace_remaining_item(
                value, pos=()
            ),
            "remaining.item.orn": lambda value: replace_remaining_item(
                value, orn=()
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(field=name):
                proxy, state, cache, transition = self._fresh_checked_transition()
                mutate(transition)
                with self.assertRaises((TypeError, ValueError)):
                    proxy.commit_transition(state, transition, cache)

    def test_commit_digest_rejects_equal_value_collection_scalar_array_and_subclass_aliases(self):
        def child_container(transition):
            return transition.child_state.containers[0]

        def child_box(transition):
            return child_container(transition).boxes[-1]

        def containers_list(transition):
            object.__setattr__(
                transition.child_state,
                "containers",
                list(transition.child_state.containers),
            )

        def remaining_list(transition):
            object.__setattr__(
                transition.child_state,
                "remaining",
                list(transition.child_state.remaining),
            )

        def supports_list(transition):
            container = child_container(transition)
            object.__setattr__(container, "supports", list(container.supports))

        def boxes_list(transition):
            container = child_container(transition)
            object.__setattr__(container, "boxes", list(container.boxes))

        def float_as_int(transition):
            container = child_container(transition)
            self.assertEqual(container.length, 2.0)
            object.__setattr__(container, "length", 2)

        def float_as_bool(transition):
            container = child_container(transition)
            self.assertEqual(container.buffer, 0.0)
            object.__setattr__(container, "buffer", False)

        def float_as_decimal(transition):
            container = child_container(transition)
            object.__setattr__(container, "width", Decimal(str(container.width)))

        def float_as_numpy_scalar(transition):
            container = child_container(transition)
            object.__setattr__(container, "center_z", np.float64(container.center_z))

        def aabb_minimum_as_list(transition):
            box = child_box(transition).box
            object.__setattr__(box, "minimum", list(box.minimum))

        def aabb_maximum_as_writeable_array(transition):
            box = child_box(transition).box
            replacement = np.array(box.maximum, dtype=np.float64, copy=True)
            self.assertTrue(replacement.flags.writeable)
            object.__setattr__(box, "maximum", replacement)

        def aabb_minimum_as_float32(transition):
            box = child_box(transition).box
            object.__setattr__(box, "minimum", np.asarray(box.minimum, dtype=np.float32))

        def aabb_axis_as_int(transition):
            box = child_box(transition).box
            object.__setattr__(box, "axis_aligned", int(box.axis_aligned))

        def nested_tag_subclass(transition):
            box = child_box(transition)
            tag = box.tag
            subclass = type("ProtectionTagAlias", (type(tag),), {})
            object.__setattr__(
                box,
                "tag",
                subclass(tag.prioritized, tag.soft),
            )

        def nested_item_subclass(transition):
            box = child_box(transition)
            item = box.item
            subclass = type("ItemSpecAlias", (ItemSpec,), {})
            object.__setattr__(
                box,
                "item",
                subclass(**{field.name: getattr(item, field.name) for field in dataclasses.fields(ItemSpec)}),
            )

        for name, mutate in {
            "containers tuple to list": containers_list,
            "remaining tuple to list": remaining_list,
            "supports tuple to list": supports_list,
            "boxes tuple to list": boxes_list,
            "float to equal int": float_as_int,
            "float to equal bool": float_as_bool,
            "float to equal Decimal": float_as_decimal,
            "float to equal numpy scalar": float_as_numpy_scalar,
            "AABB minimum to list": aabb_minimum_as_list,
            "AABB maximum to writeable ndarray": aabb_maximum_as_writeable_array,
            "AABB minimum to float32": aabb_minimum_as_float32,
            "AABB axis bool to int": aabb_axis_as_int,
            "nested protection tag subclass": nested_tag_subclass,
            "nested ItemSpec subclass": nested_item_subclass,
        }.items():
            with self.subTest(alias=name):
                proxy, state, cache, transition = self._fresh_checked_transition()
                mutate(transition)
                with self.assertRaises((TypeError, ValueError)):
                    proxy.commit_transition(state, transition, cache)

    def test_optional_pose_tuples_require_exact_python_float_components(self):
        proxy, state, _cache, transition = self._fresh_checked_transition()
        del proxy, state
        container = transition.child_state.containers[0]
        box = container.boxes[-1]
        item = dataclasses.replace(box.item, pos=(0, 0, 0), orn=(0, 0, 0, 1))
        forged_box = dataclasses.replace(box, item=item)
        forged_container = dataclasses.replace(
            container,
            boxes=container.boxes[:-1] + (forged_box,),
        )

        with self.assertRaises(TypeError):
            LayeredProxyState(
                transition.child_state.containers[:-1] + (forged_container,),
                transition.child_state.remaining,
            )

    def test_commit_rejects_transition_candidate_state_and_metrics_subclasses(self):
        for name in ("candidate", "child_state", "child_metrics"):
            with self.subTest(field=name):
                proxy, state, cache, transition = self._fresh_checked_transition()
                original = getattr(transition, name)
                subclass = type(f"{type(original).__name__}Alias", (type(original),), {})
                alias = subclass(
                    **{
                        field.name: getattr(original, field.name)
                        for field in dataclasses.fields(type(original))
                    }
                )
                object.__setattr__(transition, name, alias)

                with self.assertRaises((TypeError, ValueError)):
                    proxy.commit_transition(state, transition, cache)

    def test_commit_rejects_envelope_cache_subclasses_and_str_fingerprints(self):
        class PermissiveCache(ProxyTopologyCache):
            def owns_unchanged(self, _transition):
                return True

        class FingerprintAlias(str):
            pass

        def state_subclass(proxy, state, cache, transition):
            del proxy, cache
            subclass = type("LayeredProxyStateAlias", (LayeredProxyState,), {})
            alias = subclass(state.containers, state.remaining, state.fingerprint)
            return alias, transition, PermissiveCache()

        def transition_subclass(proxy, state, cache, transition):
            del proxy, cache
            subclass = type(
                "CheckedProxyTransitionAlias", (CheckedProxyTransition,), {}
            )
            alias = subclass(
                **{
                    field.name: getattr(transition, field.name)
                    for field in dataclasses.fields(CheckedProxyTransition)
                }
            )
            return state, alias, PermissiveCache()

        def cache_subclass(proxy, state, cache, transition):
            del proxy, cache
            return state, transition, PermissiveCache()

        def parent_state_fingerprint(proxy, state, cache, transition):
            del proxy
            object.__setattr__(state, "fingerprint", FingerprintAlias(state.fingerprint))
            return state, transition, cache

        def transition_parent_fingerprint(proxy, state, cache, transition):
            del proxy
            object.__setattr__(
                transition,
                "parent_fingerprint",
                FingerprintAlias(transition.parent_fingerprint),
            )
            return state, transition, cache

        def child_state_fingerprint(proxy, state, cache, transition):
            del proxy
            child = transition.child_state
            object.__setattr__(
                child, "fingerprint", FingerprintAlias(child.fingerprint)
            )
            return state, transition, cache

        def candidate_fingerprint(proxy, state, cache, transition):
            del proxy
            object.__setattr__(
                transition.candidate,
                "state_fingerprint",
                FingerprintAlias(transition.candidate.state_fingerprint),
            )
            return state, transition, cache

        for name, forge in {
            "parent state subclass": state_subclass,
            "transition subclass": transition_subclass,
            "permissive cache subclass": cache_subclass,
            "parent state fingerprint str subclass": parent_state_fingerprint,
            "transition parent fingerprint str subclass": transition_parent_fingerprint,
            "child state fingerprint str subclass": child_state_fingerprint,
            "candidate fingerprint str subclass": candidate_fingerprint,
        }.items():
            with self.subTest(alias=name):
                proxy, state, cache, transition = self._fresh_checked_transition()
                forged_state, forged_transition, forged_cache = forge(
                    proxy, state, cache, transition
                )
                with self.assertRaises((TypeError, ValueError)):
                    proxy.commit_transition(
                        forged_state, forged_transition, forged_cache
                    )

    def test_preview_rejects_state_key_work_quota_metrics_cache_and_fingerprint_subclasses(self):
        class FingerprintAlias(str):
            pass

        def subclass_copy(value):
            subclass = type(f"{type(value).__name__}Alias", (type(value),), {})
            return subclass(
                **{
                    field.name: getattr(value, field.name)
                    for field in dataclasses.fields(type(value))
                }
            )

        for name in (
            "state",
            "key",
            "work",
            "quota",
            "metrics",
            "cache",
            "fingerprint",
        ):
            with self.subTest(argument=name):
                proxy, state = _state()
                key = state.remaining[0].key
                work = ProxyWork()
                quota = ProxyWorkQuota(max_fit_tests=1, max_candidates=1)
                metrics = proxy.metrics(state)
                cache = ProxyTopologyCache()
                if name == "state":
                    state = subclass_copy(state)
                elif name == "key":
                    key = subclass_copy(key)
                elif name == "work":
                    work = subclass_copy(work)
                elif name == "quota":
                    quota = subclass_copy(quota)
                elif name == "metrics":
                    metrics = subclass_copy(metrics)
                elif name == "cache":
                    cache = type("ProxyTopologyCacheAlias", (ProxyTopologyCache,), {})()
                else:
                    object.__setattr__(
                        state,
                        "fingerprint",
                        FingerprintAlias(state.fingerprint),
                    )

                with self.assertRaises((TypeError, ValueError)):
                    proxy.preview_candidates(
                        state, key, work, quota, metrics, cache
                    )

    def test_cache_cannot_reregister_or_launder_original_replaced_or_metric_receipts(self):
        proxy, state = _state()
        cache = ProxyTopologyCache()
        batch = proxy.preview_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            ProxyWorkQuota(max_fit_tests=2, max_candidates=2),
            proxy.metrics(state),
            cache,
        )
        first, second = batch.transitions

        committed, _metrics = proxy.commit_transition(state, first, cache)
        self.assertIs(committed, first.child_state)

        foreign_cache = ProxyTopologyCache()
        with self.assertRaises((AttributeError, TypeError, ValueError)):
            foreign_cache.register(first)
        with self.assertRaises((TypeError, ValueError)):
            proxy.commit_transition(state, first, foreign_cache)

        matching_replacement = dataclasses.replace(
            first,
            candidate=second.candidate,
            child_state=second.child_state,
            child_metrics=second.child_metrics,
            maxrect_waste=second.maxrect_waste,
            local_cost_inputs=second.local_cost_inputs,
        )
        altered_metrics = dataclasses.replace(
            first,
            child_metrics=dataclasses.replace(
                first.child_metrics,
                low_stack=float(max(0.0, first.child_metrics.low_stack - 0.01)),
            ),
        )
        for name, forged, target_cache in (
            ("matching replacement same cache", matching_replacement, cache),
            ("matching replacement new cache", matching_replacement, ProxyTopologyCache()),
            ("altered metrics same cache", altered_metrics, cache),
            ("altered metrics new cache", altered_metrics, ProxyTopologyCache()),
        ):
            with self.subTest(receipt=name):
                with self.assertRaises((AttributeError, TypeError, ValueError)):
                    target_cache.register(forged)
                with self.assertRaises((TypeError, ValueError)):
                    proxy.commit_transition(state, forged, target_cache)

    def test_cache_copy_pickle_and_manual_dict_alias_cannot_reuse_receipts(self):
        proxy, state, cache, transition = self._fresh_checked_transition()
        committed, _metrics = proxy.commit_transition(state, transition, cache)
        self.assertIs(committed, transition.child_state)

        with self.assertRaises(TypeError):
            copy.copy(cache)
        with self.assertRaises(TypeError):
            copy.deepcopy(cache)
        with self.assertRaises(TypeError):
            pickle.dumps(cache)

        alias = object.__new__(ProxyTopologyCache)
        alias.__dict__ = cache.__dict__
        with self.assertRaises((TypeError, ValueError)):
            proxy.commit_transition(state, transition, alias)

        for rendered in (repr(cache), repr(transition)):
            lowered = rendered.lower()
            self.assertNotIn("capability", lowered)
            self.assertNotIn("issuer_seal", lowered)
            self.assertNotIn("token", lowered)
            self.assertNotIn("object at 0x", lowered)

    def test_cache_is_select_local_and_parent_and_sibling_are_immutable(self):
        proxy, state = _state()
        parent = state.fingerprint
        before = proxy.metrics(state)
        first_cache = ProxyTopologyCache()
        previews = proxy.preview_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            ProxyWorkQuota(max_fit_tests=2, max_candidates=2),
            before,
            first_cache,
        )
        first = proxy.commit_transition(state, previews.transitions[0], first_cache)[0]
        second = proxy.commit_transition(state, previews.transitions[1], first_cache)[0]

        self.assertEqual(state.fingerprint, parent)
        self.assertNotEqual(first.fingerprint, state.fingerprint)
        self.assertNotEqual(second.fingerprint, state.fingerprint)
        self.assertEqual(len(state.remaining), 2)
        self.assertGreater(first_cache.hits, 0)
        self.assertEqual(ProxyTopologyCache().hits, 0)


class MemoizedStreamingSelectorTests(unittest.TestCase):
    def test_streaming_defaults_preserve_all_legacy_work_quotas(self):
        settings, mask, _sim, _catalog = _selector_case(pool_size=1, roots=1)
        selector = MemoizedStreamingRegretProxySelector(mask, settings=settings)

        self.assertEqual(selector.max_lineages, 24)
        self.assertEqual(selector.max_depth, 12)
        self.assertEqual(selector.beam_width, 32)
        self.assertEqual(selector.proxy_quota.max_nodes, 768)
        self.assertEqual(selector.proxy_quota.max_fit_tests, 96_000)
        self.assertEqual(selector.items_per_node, 4)
        self.assertEqual(selector.placements_per_item, 3)
        self.assertEqual(selector.children_per_node, 12)
        self.assertEqual(selector.analysis_fit_quantum, 128)
        self.assertEqual(selector.occurrence_fit_quantum, 8)

    def test_ample_clock_preserves_legacy_root_identities_and_full_rank(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        kwargs = dict(
            settings=settings,
            max_depth=3,
            max_nodes=64,
            max_fit_tests=256,
            analysis_fit_quantum=64,
            clock=lambda: 0.0,
        )
        legacy = RegretProxySelector(mask, proxy=LayeredProxy(), **kwargs)
        streaming = MemoizedStreamingRegretProxySelector(
            mask, proxy=LayeredProxy(), **kwargs
        )
        parent_fingerprint = sim.fingerprint(settings)
        original_records = catalog.records

        deadline = time.perf_counter() + 100.0
        legacy_ranked = legacy.select(sim, catalog, "B", deadline)
        streaming_ranked = streaming.select(sim, catalog, "B", deadline)

        self.assertEqual(len(streaming_ranked), len(legacy_ranked))
        self.assertTrue(
            all(actual is expected for actual, expected in zip(streaming_ranked, legacy_ranked))
        )
        self.assertEqual(streaming.last_trace.ranked_keys, legacy.last_trace.ranked_keys)
        self.assertEqual(streaming.last_trace.predicted_count, legacy.last_trace.predicted_count)
        self.assertEqual(streaming.last_trace.predicted_volume, legacy.last_trace.predicted_volume)
        self.assertEqual(streaming.last_trace.nodes, legacy.last_trace.nodes)
        self.assertEqual(streaming.last_trace.fit_tests, legacy.last_trace.fit_tests)
        self.assertEqual(streaming.last_trace.candidates, legacy.last_trace.candidates)
        self.assertEqual(sim.fingerprint(settings), parent_fingerprint)
        self.assertIs(catalog.records, original_records)

    def test_deadline_after_later_analysis_retains_earlier_child_without_late_commit(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)

        hard_deadline = time.perf_counter() + 100.0

        class ToggleClock:
            expired = False

            def __call__(self):
                return hard_deadline + 1.0 if self.expired else 0.0

        clock = ToggleClock()

        class ExpiringProxy(LayeredProxy):
            preview_calls = 0
            commit_calls = 0

            def preview_candidates(self, *args, **kwargs):
                batch = super().preview_candidates(*args, **kwargs)
                self.preview_calls += 1
                if self.preview_calls == 2:
                    clock.expired = True
                return batch

            def commit_transition(self, *args, **kwargs):
                self.commit_calls += 1
                return super().commit_transition(*args, **kwargs)

        proxy = ExpiringProxy()
        selector = MemoizedStreamingRegretProxySelector(
            mask,
            proxy=proxy,
            settings=settings,
            max_depth=3,
            max_nodes=16,
            max_fit_tests=64,
            analysis_fit_quantum=1,
            clock=clock,
        )

        ranked = selector.select(sim, catalog, "B", hard_deadline)

        self.assertTrue(ranked)
        self.assertEqual(selector.last_trace.predicted_count, 2)
        self.assertEqual(selector.last_trace.committed_children, 1)
        self.assertEqual(proxy.commit_calls, 1)
        self.assertTrue(selector.last_trace.completed_partial_level)
        self.assertTrue(selector.last_trace.deadline_reached)

    def test_streamed_node_commit_does_not_steal_legacy_analysis_quota(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        kwargs = dict(
            settings=settings,
            max_depth=3,
            max_nodes=3,
            max_fit_tests=256,
            analysis_fit_quantum=64,
            clock=lambda: 0.0,
        )
        legacy = RegretProxySelector(mask, proxy=LayeredProxy(), **kwargs)
        streaming = MemoizedStreamingRegretProxySelector(
            mask, proxy=LayeredProxy(), **kwargs
        )
        deadline = time.perf_counter() + 100.0

        legacy.select(sim, catalog, "B", deadline)
        streaming.select(sim, catalog, "B", deadline)

        self.assertEqual(streaming.last_trace.fit_tests, legacy.last_trace.fit_tests)
        self.assertEqual(streaming.last_trace.candidates, legacy.last_trace.candidates)
        self.assertEqual(streaming.last_trace.ranked_keys, legacy.last_trace.ranked_keys)

    def test_c_has_no_rollout_and_only_original_roots_can_leave(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        selector = MemoizedStreamingRegretProxySelector(
            mask, settings=settings, clock=lambda: 0.0
        )

        ranked = selector.select(sim, catalog, "C", time.perf_counter() + 100.0)

        self.assertTrue(ranked)
        self.assertTrue(all(isinstance(root, ValidatedRoot) for root in ranked))
        self.assertTrue(
            all(any(root is record.root for record in catalog) for root in ranked)
        )
        self.assertEqual(selector.last_trace.committed_children, 0)
        self.assertEqual(selector.last_trace.duplicate_checks_avoided, 0)

    def test_branch_exception_preserves_best_current_catalog_root(self):
        settings, mask, sim, catalog = _selector_case(pool_size=2, roots=1)

        class BrokenPreviewProxy(LayeredProxy):
            def preview_candidates(self, *args, **kwargs):
                raise RuntimeError("isolated preview failure")

        selector = MemoizedStreamingRegretProxySelector(
            mask,
            proxy=BrokenPreviewProxy(),
            settings=settings,
            clock=lambda: 0.0,
        )

        ranked = selector.select(
            sim, catalog, "B", time.perf_counter() + 100.0
        )

        self.assertEqual(ranked, (catalog.records[0].root,))
        self.assertGreater(selector.last_trace.branch_exceptions, 0)

    def test_twenty_runs_have_identical_rank_trace_and_unchanged_work_bounds(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        outputs = []
        for _ in range(20):
            selector = MemoizedStreamingRegretProxySelector(
                mask,
                settings=settings,
                max_depth=3,
                max_nodes=64,
                max_fit_tests=256,
                analysis_fit_quantum=64,
                clock=lambda: 0.0,
            )
            ranked = selector.select(
                sim, catalog, "B", time.perf_counter() + 100.0
            )
            outputs.append((tuple(id(root) for root in ranked), selector.last_trace))

        self.assertTrue(all(value == outputs[0] for value in outputs[1:]))
        trace = outputs[0][1]
        self.assertLessEqual(trace.nodes, 64)
        self.assertLessEqual(trace.fit_tests, 256)
        self.assertLessEqual(trace.candidates, 256)
        self.assertGreater(trace.duplicate_checks_avoided, 0)
        self.assertGreater(trace.topology_cache_hits, 0)


if __name__ == "__main__":
    unittest.main()
