from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path


SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.portal_reserved_scaffold_dag.planner import build_plan  # noqa: E402
from agents.portal_reserved_scaffold_dag.portal import build_portal_edges  # noqa: E402
from agents.portal_reserved_scaffold_dag.scaffold import build_scaffold_slots  # noqa: E402


def _container(*, index: int = 0, prioritized: bool = False, shelf: bool = False) -> dict:
    return {
        "index": index,
        "length": 2.0,
        "width": 1.2,
        "height": 1.0,
        "thickness": 0.04,
        "buffer": 0.0,
        "cut_x": 0.25,
        "center": [0.0, 0.0, 0.5],
        "n_vecs": [
            [-1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, -1.0],
            [0.0, 0.0, 1.0],
        ],
        "points": [
            [-0.96, 0.0, 0.0],
            [0.96, 0.0, 0.0],
            [0.0, -0.56, 0.0],
            [0.0, 0.56, 0.0],
            [0.0, 0.0, 0.04],
            [0.0, 0.0, 0.96],
        ],
        "shelf": shelf,
        "require_shelf": shelf,
        "is_prioritized": prioritized,
        "packed_items": [],
    }


def _item(index: int, *, length: float = 0.4, width: float = 0.3, height: float = 0.2, **flags) -> dict:
    return {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "mass": 1.0,
        "is_soft": False,
        "is_prioritized": False,
        **flags,
    }


class PortalReservedScaffoldDagTests(unittest.TestCase):
    def test_floor_shelf_and_item_top_slots_record_support_and_portal_fields(self):
        # Mutation caught: omitting one support source or losing a slot's
        # support rectangle/height, load, headroom, protection, or portal.
        soft_support = {
            **_item(70, length=0.5, width=0.4, height=0.2, is_soft=True),
            "pos": [0.0, 0.1, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        container = _container(shelf=True)
        container["packed_items"] = [soft_support]
        slots = build_scaffold_slots([], [container])
        kinds = {slot.kind for slot in slots}
        self.assertIn("floor", kinds)
        self.assertIn("shelf", kinds)
        self.assertIn("item_top", kinds)
        for slot in slots:
            self.assertEqual(len(slot.support_rect), 4)
            self.assertGreaterEqual(slot.support_height, 0.0)
            self.assertGreaterEqual(slot.headroom, 0.0)
            self.assertIsInstance(slot.protection_tags, frozenset)
            self.assertEqual(len(slot.ingress_portal), 4)

    def test_deeper_wider_sweep_precedes_front_blocker(self):
        # Mutation caught: constructing portal edges from final center order
        # or X-only overlap would let a front blocker precede a deeper sweep.
        items = [
            _item(1, length=0.78, width=0.42),
            _item(2, length=0.30, width=0.30),
        ]
        front = {
            "item_index": 1,
            "container_idx": 0,
            "orientation": 0,
            "position": (0.0, -0.25, 0.15),
            "dimensions": (0.78, 0.42, 0.2),
        }
        deep = {
            "item_index": 2,
            "container_idx": 0,
            "orientation": 0,
            "position": (0.0, 0.30, 0.15),
            "dimensions": (0.30, 0.30, 0.2),
        }
        edges = build_portal_edges([front, deep], [_container()])
        self.assertTrue(any(edge.before == 2 and edge.after == 1 for edge in edges), edges)

    def test_support_edges_require_supporter_before_child(self):
        # Mutation caught: emitting a child before its item-top supporter or
        # silently dropping the support dependency from the DAG.
        supporter = {
            **_item(70, length=0.8, width=0.5, height=0.2),
            "pos": [0.0, 0.2, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        plan = build_plan(
            [_item(71, length=0.3, width=0.3, height=0.2)],
            [{**_container(), "packed_items": [supporter]}],
            time.perf_counter() + 1.0,
        )
        self.assertTrue(any(edge.before == 70 for edge in plan.support_edges), plan)
        self.assertTrue(all(edge.before != edge.after for edge in plan.support_edges))

    def test_priority_item_uses_priority_container_when_capacity_exists(self):
        # Mutation caught: treating priority-container eligibility as a soft
        # score even when an eligible prioritized container has free capacity.
        items = [_item(4, is_prioritized=True)]
        containers = [_container(index=0), _container(index=1, prioritized=True)]
        plan = build_plan(items, containers, time.perf_counter() + 1.0)
        self.assertEqual(len(plan.placements), 1)
        self.assertEqual(plan.placements[0].container_idx, 1)

    def test_soft_and_priority_supporters_expose_compatible_top_slots(self):
        # Mutation caught: placing a rigid ordinary child into a protected top
        # before considering compatible soft/priority slots.
        soft = {
            **_item(8, length=0.5, width=0.4, height=0.2, is_soft=True),
            "pos": [0.0, 0.2, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        priority = {
            **_item(9, length=0.5, width=0.4, height=0.2, is_prioritized=True),
            "pos": [0.0, -0.2, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        slots = build_scaffold_slots([], [{**_container(), "packed_items": [soft, priority]}])
        item_tops = [slot for slot in slots if slot.kind == "item_top"]
        self.assertTrue(any("soft" in slot.protection_tags for slot in item_tops))
        self.assertTrue(any("priority" in slot.protection_tags for slot in item_tops))

    def test_plan_and_action_hashes_are_stable_for_identical_inputs(self):
        # Mutation caught: hash serialization depending on set/dict iteration or
        # unstable object identity would break reproducible paired experiments.
        items = [_item(1), _item(2, length=0.5, width=0.2)]
        containers = [_container()]
        first = build_plan(items, containers, time.perf_counter() + 1.0)
        second = build_plan(items, containers, time.perf_counter() + 1.0)
        self.assertEqual(first.plan_hash, second.plan_hash)
        self.assertEqual(first.action_hash, second.action_hash)
        self.assertEqual(first["plan_hash"], first.plan_hash)


if __name__ == "__main__":
    unittest.main()
