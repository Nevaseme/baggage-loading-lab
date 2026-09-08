import math
import time
import copy
import os
import importlib.util
import numpy as np

_ORIENTATION_PERMS = (
    (0, 1, 2),
    (0, 2, 1),
    (2, 1, 0),
    (1, 0, 2),
    (1, 2, 0),
    (2, 0, 1),
)


def orientation_dims(item, orientation):
    dims = (float(item['length']), float(item['width']), float(item['height']))
    perm = _ORIENTATION_PERMS[int(orientation)]
    return dims[perm[0]], dims[perm[1]], dims[perm[2]]


def _quat_abs_rotation(quaternion):
    x, y, z, w = (float(value) for value in quaternion)
    norm = math.sqrt(x*x + y*y + z*z + w*w)
    if norm <= 1e-12:
        return np.eye(3, dtype=np.float64)
    x, y, z, w = x/norm, y/norm, z/norm, w/norm
    return np.abs(np.asarray([
        (1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)),
        (2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)),
        (2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)),
    ], dtype=np.float64))


def packed_aabb(item, container_offset_x):
    pos = item.get('pos')
    orn = item.get('orn')
    if pos is None or orn is None:
        return None
    half = np.asarray((
        float(item['length']) * 0.5,
        float(item['width']) * 0.5,
        float(item['height']) * 0.5,
    ), dtype=np.float64)
    extent = _quat_abs_rotation(orn).dot(half)
    center = np.asarray((
        float(pos[0]) - float(container_offset_x),
        float(pos[1]),
        float(pos[2]),
    ), dtype=np.float64)
    return center - extent, center + extent


def _container_offset_x(container):
    center = container.get('center', (0.0, 0.0, 0.0))
    return 0.0 if center is None else float(center[0])


def _local_planes(container):
    normals = np.asarray(container.get('n_vecs', []), dtype=np.float64)
    points = np.asarray(container.get('points', []), dtype=np.float64)
    if len(normals) and len(normals) == len(points):
        points = points.copy()
        offset = _container_offset_x(container)
        if abs(float(np.mean(points[:, 0])) - offset) <= max(float(container.get('length', 2.0)), 1.0):
            points[:, 0] -= offset
        return normals, points

    length = float(container['length'])
    width = float(container['width'])
    height = float(container['height'])
    thickness = float(container.get('thickness', 0.04))
    buffer = float(container.get('buffer', 0.01))
    floor = thickness + buffer
    normals = np.asarray([
        (-1, 0, 0), (1, 0, 0), (0, -1, 0),
        (0, 1, 0), (0, 0, -1), (0, 0, 1),
    ], dtype=np.float64)
    points = np.asarray([
        (-length/2 + thickness, 0, 0),
        (length/2 - thickness, 0, 0),
        (0, -width/2 + thickness, 0),
        (0, width/2 - thickness, 0),
        (0, 0, floor),
        (0, 0, height + buffer - thickness),
    ], dtype=np.float64)
    return normals, points


def _candidate_corners(center, dims):
    center = np.asarray(center, dtype=np.float64)
    half = np.asarray(dims, dtype=np.float64) * 0.5
    signs = np.asarray([
        (-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
        (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1),
    ], dtype=np.float64)
    return center + signs * half


def _inside_container(container, center, dims, margin=-0.005):
    normals, points = _local_planes(container)
    corners = _candidate_corners(center, dims)
    values = ((corners[:, None, :] - points[None, :, :]) * normals[None, :, :]).sum(axis=2)
    return bool(np.all(values <= float(margin) + 1e-10))


def _floor_z(container):
    normals, points = _local_planes(container)
    for normal, point in zip(normals, points):
        if normal[2] < -0.9 and abs(normal[0]) < 0.1 and abs(normal[1]) < 0.1:
            return float(point[2])
    return float(container.get('thickness', 0.04)) + float(container.get('buffer', 0.01))


def _rect_intersection(first, second):
    x0 = max(float(first[0]), float(second[0]))
    x1 = min(float(first[1]), float(second[1]))
    y0 = max(float(first[2]), float(second[2]))
    y1 = min(float(first[3]), float(second[3]))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, x1, y0, y1


def _rect_union_area(rectangles):
    if not rectangles:
        return 0.0
    xs = sorted({float(rect[0]) for rect in rectangles} | {float(rect[1]) for rect in rectangles})
    area = 0.0
    for xa, xb in zip(xs[:-1], xs[1:]):
        if xb <= xa:
            continue
        midpoint = 0.5 * (xa + xb)
        intervals = sorted(
            (float(rect[2]), float(rect[3]))
            for rect in rectangles
            if float(rect[0]) <= midpoint <= float(rect[1])
        )
        if not intervals:
            continue
        start, end = intervals[0]
        covered = 0.0
        for next_start, next_end in intervals[1:]:
            if next_start <= end:
                end = max(end, next_end)
            else:
                covered += end - start
                start, end = next_start, next_end
        covered += end - start
        area += (xb - xa) * covered
    return area


def _support_metrics(center, dims, supports, z_tolerance=0.025):
    center = np.asarray(center, dtype=np.float64)
    dx, dy, dz = (float(value) for value in dims)
    bottom = float(center[2] - dz * 0.5)
    footprint = (
        float(center[0] - dx * 0.5), float(center[0] + dx * 0.5),
        float(center[1] - dy * 0.5), float(center[1] + dy * 0.5),
    )
    intersections = []
    used = []
    center_supported = False
    for support in supports:
        if abs(float(support['z']) - bottom) > float(z_tolerance):
            continue
        intersection = _rect_intersection(footprint, support['rect'])
        if intersection is None:
            continue
        intersections.append(intersection)
        used.append(support)
        x0, x1, y0, y1 = (float(value) for value in support['rect'])
        if x0 - 1e-9 <= center[0] <= x1 + 1e-9 and y0 - 1e-9 <= center[1] <= y1 + 1e-9:
            center_supported = True
    ratio = min(1.0, _rect_union_area(intersections) / max(dx * dy, 1e-12))
    return float(ratio), bool(center_supported), used


def _aabb_overlap(lo_a, hi_a, lo_b, hi_b, tolerance=0.001):
    for axis in range(3):
        if float(hi_a[axis]) <= float(lo_b[axis]) + tolerance:
            return False
        if float(hi_b[axis]) <= float(lo_a[axis]) + tolerance:
            return False
    return True


def _target_clear(center, dims, boxes):
    center = np.asarray(center, dtype=np.float64)
    half = np.asarray(dims, dtype=np.float64) * 0.5
    lo, hi = center - half, center + half
    return not any(_aabb_overlap(lo, hi, box_lo, box_hi) for box_lo, box_hi, _ in boxes)


def _effective_path_z(container, center, dims):
    center = np.asarray(center, dtype=np.float64)
    half = np.asarray(dims, dtype=np.float64) * 0.5
    thickness = float(container.get('thickness', 0.04))
    height = float(container['height'])
    buffer = float(container.get('buffer', 0.01))
    effective_start = 0.08
    bottom = float(center[2] - half[2])
    for resting_z in (thickness, height * 0.5 + thickness + buffer):
        if 0.0 <= bottom - resting_z <= 0.05:
            effective_start = 0.0
            break
    top = float(center[2] + half[2])
    if effective_start > 0.0:
        for ceiling_z in (height * 0.5 + buffer, height + buffer - thickness):
            clearance = ceiling_z - top
            if 0.0 <= clearance < effective_start + 0.018:
                effective_start = max(0.0, clearance - 0.018 - 0.0005)
                break
    return min(height + buffer - thickness - half[2] - 0.01, float(center[2] + effective_start))


def _transport_clear(container, center, dims, packed_boxes, shelves=None, safety_margin=0.015):
    center = np.asarray(center, dtype=np.float64)
    half = np.asarray(dims, dtype=np.float64) * 0.5
    length = float(container['length'])
    width = float(container['width'])
    thickness = float(container.get('thickness', 0.04))
    cut_x = float(container.get('cut_x', 0.0))
    start_x_min = -length * 0.5 + thickness + cut_x + half[0] + 0.01
    start_x_max = length * 0.5 - thickness - half[0] - 0.01
    start_x = min(max(float(center[0]), start_x_min), start_x_max) if start_x_min <= start_x_max else float(center[0])
    path_z = _effective_path_z(container, center, dims)
    margin = float(safety_margin)
    obstacles = list(packed_boxes) + list(shelves or [])

    segment_y_lo = np.asarray((
        start_x - half[0] - margin,
        min(-width * 0.5, float(center[1])) - half[1] - margin,
        path_z - half[2] - margin,
    ), dtype=np.float64)
    segment_y_hi = np.asarray((
        start_x + half[0] + margin,
        max(-width * 0.5, float(center[1])) + half[1] + margin,
        path_z + half[2] + margin,
    ), dtype=np.float64)
    segment_x_lo = np.asarray((
        min(start_x, float(center[0])) - half[0] - margin,
        float(center[1]) - half[1] - margin,
        path_z - half[2] - margin,
    ), dtype=np.float64)
    segment_x_hi = np.asarray((
        max(start_x, float(center[0])) + half[0] + margin,
        float(center[1]) + half[1] + margin,
        path_z + half[2] + margin,
    ), dtype=np.float64)
    for box_lo, box_hi, _ in obstacles:
        if _aabb_overlap(segment_y_lo, segment_y_hi, box_lo, box_hi, tolerance=0.0):
            return False
        if _aabb_overlap(segment_x_lo, segment_x_hi, box_lo, box_hi, tolerance=0.0):
            return False
    return True


def _candidate_valid(item, container, dims, center, packed_boxes, shelves, supports, minimum_support_ratio=0.62):
    # The public action is serialized as float32.  A float64 candidate exactly
    # on the official -5 mm inclusion boundary can round a few nanometres
    # outward and be rejected by the evaluator.  Authorize the exact formatted
    # coordinate that will be returned, and use it for every downstream guard.
    center = np.asarray(center, dtype=np.float32).astype(np.float64)
    if not _inside_container(container, center, dims, margin=-0.005):
        return False, {'reason': 'inclusion'}
    if not _target_clear(center, dims, list(packed_boxes) + list(shelves)):
        return False, {'reason': 'target_collision'}
    support_ratio, center_supported, supporters = _support_metrics(center, dims, supports)
    if not center_supported or support_ratio < float(minimum_support_ratio):
        return False, {
            'reason': 'support',
            'support_ratio': support_ratio,
            'center_supported': center_supported,
            'supporters': supporters,
        }
    if not bool(item.get('is_soft', False)):
        for support in supporters:
            if support.get('kind') == 'item' and bool(support.get('meta', {}).get('is_soft', False)):
                return False, {'reason': 'soft_support', 'support_ratio': support_ratio, 'supporters': supporters}
    if not _transport_clear(container, center, dims, packed_boxes, shelves, safety_margin=0.015):
        return False, {'reason': 'transport', 'support_ratio': support_ratio, 'supporters': supporters}
    return True, {
        'reason': 'ok',
        'support_ratio': support_ratio,
        'center_supported': center_supported,
        'supporters': supporters,
    }


def _inner_xy_bounds(container):
    normals, points = _local_planes(container)
    length = float(container['length'])
    width = float(container['width'])
    thickness = float(container.get('thickness', 0.04))
    x_min = -length * 0.5 + thickness
    x_max = length * 0.5 - thickness
    y_min = -width * 0.5 + thickness
    y_max = width * 0.5 - thickness
    for normal, point in zip(normals, points):
        if normal[0] < -0.9 and abs(normal[1]) < 0.1 and abs(normal[2]) < 0.1:
            x_min = max(x_min, float(point[0]))
        elif normal[0] > 0.9 and abs(normal[1]) < 0.1 and abs(normal[2]) < 0.1:
            x_max = min(x_max, float(point[0]))
        elif normal[1] < -0.9 and abs(normal[0]) < 0.1 and abs(normal[2]) < 0.1:
            y_min = max(y_min, float(point[1]))
        elif normal[1] > 0.9 and abs(normal[0]) < 0.1 and abs(normal[2]) < 0.1:
            y_max = min(y_max, float(point[1]))
    return float(x_min), float(x_max), float(y_min), float(y_max)


def _packed_boxes(container):
    offset = _container_offset_x(container)
    boxes = []
    for item in container.get('packed_items', []):
        box = packed_aabb(item, offset)
        if box is not None:
            boxes.append((box[0], box[1], item))
    return boxes


def _shelf_boxes(container):
    length = float(container['length'])
    width = float(container['width'])
    height = float(container['height'])
    thickness = float(container.get('thickness', 0.04))
    cut_x = float(container.get('cut_x', 0.0))
    buffer = float(container.get('buffer', 0.01))
    top = height * 0.5 + thickness + buffer
    boxes = []
    if cut_x > 1e-9:
        boxes.append((
            np.asarray((-length/2 + thickness, -width/2 + thickness, top - thickness), dtype=np.float64),
            np.asarray((-length/2 + thickness + cut_x, width/2 - thickness, top), dtype=np.float64),
            {'kind': 'small_shelf', 'mass': 1e12, 'is_soft': False, 'is_prioritized': False},
        ))
    if bool(container.get('shelf', False)):
        boxes.append((
            np.asarray((-length/2 + thickness/2, thickness, top - thickness), dtype=np.float64),
            np.asarray((length/2 - thickness/2, width/2 - thickness, top), dtype=np.float64),
            {'kind': 'shelf', 'mass': 1e12, 'is_soft': False, 'is_prioritized': False},
        ))
    return boxes


def _support_surfaces(container):
    x0, x1, y0, y1 = _inner_xy_bounds(container)
    surfaces = [{
        'rect': (x0, x1, y0, y1),
        'z': _floor_z(container),
        'kind': 'floor',
        'meta': {'mass': 1e12, 'is_soft': False, 'is_prioritized': False},
    }]
    for lo, hi, meta in _shelf_boxes(container):
        surfaces.append({
            'rect': (float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1])),
            'z': float(hi[2]),
            'kind': str(meta['kind']),
            'meta': meta,
        })
    for lo, hi, item in _packed_boxes(container):
        surfaces.append({
            'rect': (float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1])),
            'z': float(hi[2]),
            'kind': 'item',
            'meta': item,
        })
    return surfaces


def _candidate_centers(container, dims, supports, packed_boxes, max_candidates=320):
    dx, dy, dz = (float(value) for value in dims)
    support_lists = []
    for support in sorted(supports, key=lambda value: (-float(value['rect'][3]), float(value['z']), value['kind'])):
        x0, x1, y0, y1 = (float(value) for value in support['rect'])
        kind = support['kind']
        if kind == 'item':
            if x1 - x0 < 0.45 * dx or y1 - y0 < 0.45 * dy:
                continue
            x_mid = 0.5 * (x0 + x1)
            y_mid = 0.5 * (y0 + y1)
            x_values = [x_mid, x0 + dx/2, x1 - dx/2, x0, x1]
            y_values = [y_mid, y1 - dy/2, y0 + dy/2, y1, y0]
            x_allow = (x0 - dx/2, x1 + dx/2)
            y_allow = (y0 - dy/2, y1 + dy/2)
            gap = 0.006
        else:
            inset = 0.008 if kind == 'floor' else 0.004
            x_lo, x_hi = x0 + dx/2 + inset, x1 - dx/2 - inset
            y_lo, y_hi = y0 + dy/2 + inset, y1 - dy/2 - inset
            if x_lo > x_hi or y_lo > y_hi:
                continue
            x_mid = min(max(0.0, x_lo), x_hi)
            x_values = [x_lo, x_hi, x_mid, 0.5*(x_lo+x_mid), 0.5*(x_mid+x_hi)]
            y_values = [y_hi, y_lo, 0.5*(y_lo+y_hi)]
            x_allow = (x_lo, x_hi)
            y_allow = (y_lo, y_hi)
            gap = 0.008 if kind == 'floor' else 0.018

            nearby = [
                box for box in packed_boxes
                if abs(float(box[0][2]) - float(support['z'])) <= 0.09
            ]
            nearby.sort(key=lambda box: (-float(box[1][1]), float(box[0][0])))
            for lo, hi, _ in nearby[:12]:
                x_values.extend((float(lo[0]) - dx/2 - 0.018, float(hi[0]) + dx/2 + 0.018))
                y_values.append(float(lo[1]) - dy/2 - 0.018)

        z = float(support['z']) + gap + dz/2
        x_values = sorted(
            {round(float(x), 6) for x in x_values if x_allow[0]-1e-9 <= x <= x_allow[1]+1e-9},
            key=lambda x: (abs(x), x),
        )
        y_values = sorted(
            {round(float(y), 6) for y in y_values if y_allow[0]-1e-9 <= y <= y_allow[1]+1e-9},
            reverse=True,
        )
        local = []
        seen = set()
        for y in y_values:
            for x in x_values:
                point = (float(x), float(y), float(z))
                key = tuple(round(value, 5) for value in point)
                if key in seen or not _inside_container(container, point, dims, margin=-0.005):
                    continue
                seen.add(key)
                local.append(point)
        if local:
            support_lists.append(local)

    output = []
    seen = set()
    depth = 0
    while len(output) < max(0, int(max_candidates)):
        added = False
        for local in support_lists:
            if depth >= len(local):
                continue
            point = local[depth]
            key = tuple(round(value, 5) for value in point)
            if key not in seen:
                seen.add(key)
                output.append(point)
                if len(output) >= max_candidates:
                    break
            added = True
        if not added:
            break
        depth += 1
    return output


def _ingress_shadow_cost(container, center, dims, supports):
    center = np.asarray(center, dtype=np.float64)
    dx, dy, dz = (float(value) for value in dims)
    candidate_x0 = float(center[0] - dx/2 - 0.015)
    candidate_x1 = float(center[0] + dx/2 + 0.015)
    candidate_back = float(center[1] + dy/2 + 0.015)
    candidate_top = float(center[2] + dz/2)
    x_min, x_max, y_min, y_max = _inner_xy_bounds(container)
    normalizer = max((x_max-x_min) * (y_max-y_min), 1e-9)
    blocked = 0.0
    for support in supports:
        sx0, sx1, sy0, sy1 = (float(value) for value in support['rect'])
        overlap_x = max(0.0, min(candidate_x1, sx1) - max(candidate_x0, sx0))
        deeper_length = max(0.0, sy1 - max(candidate_back, sy0))
        if overlap_x <= 0.0 or deeper_length <= 0.0:
            continue
        height_weight = 1.0 if float(support['z']) <= candidate_top + 0.10 else 0.35
        kind_weight = 1.0 if support['kind'] in {'floor', 'shelf', 'small_shelf'} else 0.65
        blocked += overlap_x * deeper_length * height_weight * kind_weight
    return float(blocked / normalizer)


def _residual_strip_score(support, center, dims, sliver_ratio=0.28):
    x0, x1, y0, y1 = (float(value) for value in support['rect'])
    cx, cy = float(center[0]), float(center[1])
    dx, dy = float(dims[0]), float(dims[1])
    gaps = (
        cx - dx/2 - x0,
        x1 - (cx + dx/2),
        cy - dy/2 - y0,
        y1 - (cy + dy/2),
    )
    threshold = max(0.025, min(dx, dy) * float(sliver_ratio))
    score = 0.0
    for gap in gaps:
        if abs(gap) <= 0.012:
            score += 0.25
        elif 0.0 < gap < threshold:
            score -= (threshold-gap) / threshold
    return float(score)


def _primary_support(metrics):
    supporters = list(metrics.get('supporters', []))
    if not supporters:
        return None
    rank = {'item': 0, 'shelf': 1, 'small_shelf': 1, 'floor': 2}
    return min(supporters, key=lambda value: (rank.get(value.get('kind'), 3), -float(value.get('z', 0.0))))


def _score_candidate(item, container, dims, center, metrics, supports, packed_boxes, all_containers, pool_size=1):
    dx, dy, dz = (float(value) for value in dims)
    x, y, z = (float(value) for value in center)
    volume = dx * dy * dz
    mass = float(item.get('mass', 1.0))
    height = max(float(container['height']), 1e-9)
    width = max(float(container['width']), 1e-9)
    container_volume = max(float(container.get('volume', float(container['length'])*width*height)), 1e-9)
    z_norm = max(0.0, z / height)
    backness = max(0.0, min(1.0, (y + width/2) / width))
    support_ratio = float(metrics.get('support_ratio', 0.0))
    soft = bool(item.get('is_soft', False))
    priority = bool(item.get('is_prioritized', False))

    score = 12.0 * support_ratio
    score += 115.0 * volume / container_volume
    score -= (2.5 + 0.34*mass) * z_norm
    score += 2.2 * min(1.0, (dx*dy) / max(volume ** (2.0/3.0), 1e-9))
    if soft or priority:
        score += 2.0 * (1.0-backness) + 0.5*z_norm
    else:
        score += 7.0 * backness

    shadow = _ingress_shadow_cost(container, center, dims, supports)
    score -= 20.0 * shadow
    primary = _primary_support(metrics)
    if primary is not None:
        score += 2.5 * _residual_strip_score(primary, center, dims)
        if primary.get('kind') == 'item' and y > 0.0:
            score += 4.0
        elif primary.get('kind') == 'floor' and y < -0.05 and packed_boxes:
            score -= 2.5

    # Priority baggage may physically support another box, but doing so incurs
    # an official placement penalty.  Keep it a soft objective (not a hard gate)
    # so late-stage feasibility is not destroyed as in earlier low-scoring
    # variants.
    if not priority and any(
        supporter.get('kind') == 'item'
        and bool(supporter.get('meta', {}).get('is_prioritized', False))
        for supporter in metrics.get('supporters', [])
    ):
        score -= 18.0

    priority_containers = [value for value in all_containers if bool(value.get('is_prioritized', False))]
    if priority_containers:
        if priority:
            score += 30.0 if bool(container.get('is_prioritized', False)) else -36.0
        elif bool(container.get('is_prioritized', False)):
            score -= 6.0
    return float(score)


def _unique_orientations(item):
    seen = set()
    values = []
    for orientation in range(6):
        dims = orientation_dims(item, orientation)
        key = tuple(round(float(value), 8) for value in dims)
        if key in seen:
            continue
        seen.add(key)
        values.append((orientation, dims))
    values.sort(key=lambda entry: (entry[1][2], -(entry[1][0]*entry[1][1]), entry[0]))
    return values


def _item_urgency(item):
    length = float(item['length'])
    width = float(item['width'])
    height = float(item['height'])
    volume = length * width * height
    mass = float(item.get('mass', 1.0))
    value = 42.0*volume + 0.055*mass + 0.35*max(length, width, height)
    if bool(item.get('is_soft', False)):
        value -= 1.35
    if bool(item.get('is_prioritized', False)):
        value -= 0.20
    return float(value)


def _enumerate_candidates(observation, *, deadline, max_checks=18000, per_orientation_limit=180):
    pool = list(observation.get('pool_list', []))
    containers = list(observation.get('container_list', []))
    if not pool or not containers:
        return []

    ordered_items = sorted(
        range(len(pool)),
        key=lambda index: (-_item_urgency(pool[index]), int(pool[index].get('index', index)), index),
    )
    minimum_item_quota = min(64, max(12, int(max_checks) // max(1, len(pool)*3)))
    item_quota = max(minimum_item_quota, int(max_checks) // max(1, len(pool)))
    results = []
    checks = 0

    for pool_index in ordered_items:
        if time.perf_counter() >= deadline or checks >= max_checks:
            break
        item = pool[pool_index]
        orientations = _unique_orientations(item)
        slot_count = max(1, len(containers) * len(orientations))
        slot_quota = max(4, item_quota // slot_count)
        item_checks = 0
        for container_index, container in enumerate(containers):
            if time.perf_counter() >= deadline or checks >= max_checks or item_checks >= item_quota:
                break
            packed = _packed_boxes(container)
            shelves = _shelf_boxes(container)
            supports = _support_surfaces(container)
            for orientation, dims in orientations:
                if time.perf_counter() >= deadline or checks >= max_checks or item_checks >= item_quota:
                    break
                if (dims[0] > float(container['length']) + 1e-9
                        or dims[1] > float(container['width']) + 1e-9
                        or dims[2] > float(container['height']) + 1e-9):
                    continue
                points = _candidate_centers(
                    container,
                    dims,
                    supports,
                    packed,
                    max_candidates=min(int(per_orientation_limit), max(slot_quota*3, 18)),
                )
                slot_checks = 0
                for center in points:
                    if (time.perf_counter() >= deadline or checks >= max_checks
                            or item_checks >= item_quota or slot_checks >= slot_quota):
                        break
                    slot_checks += 1
                    item_checks += 1
                    checks += 1
                    valid, metrics = _candidate_valid(item, container, dims, center, packed, shelves, supports)
                    if not valid:
                        continue
                    score = _score_candidate(
                        item,
                        container,
                        dims,
                        center,
                        metrics,
                        supports,
                        packed,
                        containers,
                        pool_size=len(pool),
                    )
                    results.append({
                        'item_idx': int(pool_index),
                        'container_idx': int(container_index),
                        'place_pos': np.asarray(center, dtype=np.float32),
                        'orientation': int(orientation),
                        'score': float(score),
                        'support_ratio': float(metrics.get('support_ratio', 0.0)),
                        'shadow_cost': float(_ingress_shadow_cost(container, center, dims, supports)),
                    })

    results.sort(key=lambda candidate: (
        float(candidate['score']),
        -float(candidate['place_pos'][2]),
        float(candidate['place_pos'][1]),
        -abs(float(candidate['place_pos'][0])),
        -int(candidate['orientation']),
        -int(candidate['item_idx']),
        -int(candidate['container_idx']),
    ), reverse=True)
    return results


def _choose_candidate(candidates, pool, containers):
    if not candidates:
        return None
    grouped = {}
    for candidate in candidates:
        grouped.setdefault(int(candidate['item_idx']), []).append(candidate)
    packed_count = sum(len(container.get('packed_items', [])) for container in containers)
    rigid_available = any(
        not bool(pool[index].get('is_soft', False))
        and not bool(pool[index].get('is_prioritized', False))
        for index in grouped
    )
    best_choice = None
    best_key = None
    for pool_index, values in grouped.items():
        ordered = sorted(values, key=lambda value: (
            float(value['score']),
            -float(value['place_pos'][2]),
            float(value['place_pos'][1]),
            -abs(float(value['place_pos'][0])),
            -int(value['orientation']),
        ), reverse=True)
        best = ordered[0]
        second_score = float(ordered[1]['score']) if len(ordered) > 1 else float(best['score']) - 1.8
        regret = min(4.0, max(0.0, float(best['score']) - second_score))
        scarcity = 1.2 / math.sqrt(max(1, len(ordered)))
        item = pool[pool_index]
        selection_score = float(best['score']) + 0.9*regret + scarcity + 0.30*_item_urgency(item)
        if rigid_available and (bool(item.get('is_soft', False)) or bool(item.get('is_prioritized', False))):
            if packed_count < 18:
                selection_score -= 2.8
            elif packed_count >= 24:
                selection_score += 0.8
        key = (
            selection_score,
            float(best['score']),
            -len(ordered),
            -int(pool_index),
        )
        if best_key is None or key > best_key:
            best_key = key
            best_choice = best
    return best_choice


def _dense_support_points(container, dims, supports, packed_boxes):
    dx, dy, dz = (float(value) for value in dims)
    points = list(_candidate_centers(container, dims, supports, packed_boxes, max_candidates=700))
    for support in supports:
        x0, x1, y0, y1 = (float(value) for value in support['rect'])
        kind = support['kind']
        if kind == 'item':
            x_lo, x_hi = x0 - dx/2, x1 + dx/2
            y_lo, y_hi = y0 - dy/2, y1 + dy/2
            gap = 0.006
        else:
            inset = 0.008 if kind == 'floor' else 0.004
            x_lo, x_hi = x0 + dx/2 + inset, x1 - dx/2 - inset
            y_lo, y_hi = y0 + dy/2 + inset, y1 - dy/2 - inset
            gap = 0.008 if kind == 'floor' else 0.018
        if x_lo > x_hi or y_lo > y_hi:
            continue
        z = float(support['z']) + gap + dz/2
        for y in np.linspace(y_hi, y_lo, 9):
            for x in np.linspace(x_lo, x_hi, 9):
                point = (float(x), float(y), float(z))
                if _inside_container(container, point, dims, margin=-0.005):
                    points.append(point)
    unique = {}
    for point in points:
        unique.setdefault(tuple(round(float(value), 5) for value in point), point)
    return sorted(unique.values(), key=lambda point: (point[2], -point[1], abs(point[0])))


def _dense_recovery(observation, *, deadline, max_checks=12000):
    pool = list(observation.get('pool_list', []))
    containers = list(observation.get('container_list', []))
    if not pool or not containers:
        return None
    item_order = sorted(range(len(pool)), key=lambda index: (
        float(pool[index]['length'])*float(pool[index]['width'])*float(pool[index]['height']),
        max(float(pool[index]['length']), float(pool[index]['width']), float(pool[index]['height'])),
        float(pool[index].get('mass', 1.0)),
        index,
    ))
    checks = 0
    for pool_index in item_order:
        item = pool[pool_index]
        container_order = list(range(len(containers)))
        if bool(item.get('is_prioritized', False)):
            container_order.sort(key=lambda index: (not bool(containers[index].get('is_prioritized', False)), index))
        for container_index in container_order:
            container = containers[container_index]
            packed = _packed_boxes(container)
            shelves = _shelf_boxes(container)
            supports = _support_surfaces(container)
            for orientation, dims in _unique_orientations(item):
                if time.perf_counter() >= deadline or checks >= max_checks:
                    return None
                if (dims[0] > float(container['length']) + 1e-9
                        or dims[1] > float(container['width']) + 1e-9
                        or dims[2] > float(container['height']) + 1e-9):
                    continue
                for center in _dense_support_points(container, dims, supports, packed):
                    if time.perf_counter() >= deadline or checks >= max_checks:
                        return None
                    checks += 1
                    valid, _ = _candidate_valid(item, container, dims, center, packed, shelves, supports)
                    if valid:
                        return {
                            'item_idx': int(pool_index),
                            'container_idx': int(container_index),
                            'place_pos': np.asarray(center, dtype=np.float32),
                            'orientation': int(orientation),
                        }
    return None


def _support_relaxed_recovery(observation, *, deadline, max_checks=16000):
    """Final verified rescue using a 58% support floor.

    The official process validator has no analytic support-ratio gate; it judges
    the actual settling displacement and angle.  Use this stage only after the
    conservative 62% catalog is empty, while preserving inclusion, target,
    transport, COM support, and hard-on-soft prohibitions.
    """
    pool = list(observation.get('pool_list', []))
    containers = list(observation.get('container_list', []))
    if not pool or not containers:
        return None
    item_order = sorted(range(len(pool)), key=lambda index: (
        float(pool[index]['length'])*float(pool[index]['width'])*float(pool[index]['height']),
        float(pool[index].get('mass', 1.0)),
        index,
    ))
    checks = 0
    best = None
    best_key = None
    for pool_index in item_order:
        item = pool[pool_index]
        for container_index, container in enumerate(containers):
            packed = _packed_boxes(container)
            shelves = _shelf_boxes(container)
            supports = _support_surfaces(container)
            for orientation, dims in _unique_orientations(item):
                if time.perf_counter() >= deadline or checks >= max_checks:
                    return best
                for center in _dense_support_points(container, dims, supports, packed):
                    if time.perf_counter() >= deadline or checks >= max_checks:
                        return best
                    checks += 1
                    valid, metrics = _candidate_valid(
                        item,
                        container,
                        dims,
                        center,
                        packed,
                        shelves,
                        supports,
                        minimum_support_ratio=0.58,
                    )
                    if not valid:
                        continue
                    support_ratio = float(metrics.get('support_ratio', 0.0))
                    if support_ratio >= 0.62:
                        # Strict recovery should already have returned this; keep
                        # this stage single-purpose and deterministic.
                        continue
                    point = np.asarray(center, dtype=np.float32)
                    shadow = _ingress_shadow_cost(container, point, dims, supports)
                    key = (
                        support_ratio,
                        -float(point[2]),
                        float(point[1]),
                        -shadow,
                        -abs(float(point[0])),
                        -int(pool_index),
                    )
                    if best_key is None or key > best_key:
                        best_key = key
                        best = {
                            'item_idx': int(pool_index),
                            'container_idx': int(container_index),
                            'place_pos': point,
                            'orientation': int(orientation),
                        }
    return best


def _contained_last_resort(observation):
    pool = list(observation.get('pool_list', []))
    containers = list(observation.get('container_list', []))
    if not pool or not containers:
        return {
            'item_idx': 0,
            'container_idx': 0,
            'place_pos': np.asarray((0.0, 0.0, 0.1), dtype=np.float32),
            'orientation': 0,
        }
    pool_index = min(range(len(pool)), key=lambda index: (
        float(pool[index]['length'])*float(pool[index]['width'])*float(pool[index]['height']), index
    ))
    item = pool[pool_index]
    container_index = 0
    if bool(item.get('is_prioritized', False)):
        for index, container in enumerate(containers):
            if bool(container.get('is_prioritized', False)):
                container_index = index
                break
    container = containers[container_index]
    orientation, dims = _unique_orientations(item)[0]
    floor = _floor_z(container)
    x0, x1, y0, y1 = _inner_xy_bounds(container)
    center = (
        min(max(0.0, x0+dims[0]/2+0.008), x1-dims[0]/2-0.008),
        y0+dims[1]/2+0.008,
        floor+dims[2]/2+0.008,
    )
    return {
        'item_idx': int(pool_index),
        'container_idx': int(container_index),
        'place_pos': np.asarray(center, dtype=np.float32),
        'orientation': int(orientation),
    }



_ORIENTATION_EULERS = (
    (0.0, 0.0, 0.0),
    (math.pi/2, 0.0, 0.0),
    (0.0, math.pi/2, 0.0),
    (0.0, 0.0, math.pi/2),
    (0.0, math.pi/2, math.pi/2),
    (math.pi/2, 0.0, math.pi/2),
)


def _quat_from_euler(roll, pitch, yaw):
    cr, sr = math.cos(roll/2), math.sin(roll/2)
    cp, sp = math.cos(pitch/2), math.sin(pitch/2)
    cy, sy = math.cos(yaw/2), math.sin(yaw/2)
    return (
        sr*cp*cy - cr*sp*sy,
        cr*sp*cy + sr*cp*sy,
        cr*cp*sy - sr*sp*cy,
        cr*cp*cy + sr*sp*sy,
    )


def _offline_static_key(item):
    soft = bool(item.get('is_soft', False))
    priority = bool(item.get('is_prioritized', False))
    if not soft and not priority:
        group = 0
    elif priority and not soft:
        group = 1
    elif soft and priority:
        group = 3
    else:
        group = 2
    length = float(item['length'])
    width = float(item['width'])
    height = float(item['height'])
    volume = length*width*height
    footprint = max(length*width, length*height, width*height)
    mass = float(item.get('mass', 1.0))
    return (group, -mass, -footprint, -volume, -max(length, width, height), int(item['index']))


def _virtual_add(container, item, action, metrics):
    placed = dict(item)
    target = np.asarray(action['place_pos'], dtype=np.float64)
    dims = orientation_dims(item, int(action['orientation']))
    supporters = list(metrics.get('supporters', []))
    if supporters:
        support_z = max(float(support['z']) for support in supporters)
        settled_z = support_z + float(dims[2])*0.5
    else:
        settled_z = float(target[2])
    offset = _container_offset_x(container)
    placed['pos'] = (float(target[0])+offset, float(target[1]), float(settled_z))
    placed['orn'] = _quat_from_euler(*_ORIENTATION_EULERS[int(action['orientation'])])
    placed['belongs_to'] = int(container.get('index', 0))
    container.setdefault('packed_items', []).append(placed)


def _authorized_planned_action(agent, observation):
    if not observation.get('optimize') or not agent.offline_plan:
        return None
    pool = list(observation.get('pool_list', []))
    containers = list(observation.get('container_list', []))
    planned = []
    for pool_index, item in enumerate(pool):
        item_id = int(item.get('index', -1))
        plan = agent.offline_plan.get(item_id)
        if plan is not None:
            planned.append((agent.offline_rank.get(item_id, 10**9), pool_index, item, plan))
    planned.sort(key=lambda row: (row[0], row[1]))
    for _rank, pool_index, item, plan in planned:
        container_index = int(plan.get('container_idx', -1))
        orientation = int(plan.get('orientation', -1))
        center = np.asarray(plan.get('place_pos'), dtype=np.float64)
        if not (0 <= container_index < len(containers) and 0 <= orientation < 6 and center.shape == (3,)):
            continue
        container = containers[container_index]
        dims = orientation_dims(item, orientation)
        valid, _ = _candidate_valid(
            item,
            container,
            dims,
            center,
            _packed_boxes(container),
            _shelf_boxes(container),
            _support_surfaces(container),
        )
        if valid:
            return {
                'item_idx': int(pool_index),
                'container_idx': int(container_index),
                'place_pos': np.asarray(center, dtype=np.float32),
                'orientation': int(orientation),
            }
    return None


def _load_seed_planner():
    """Load the proven conservative column-scaffold planner from this package."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'column_scaffold_planner.py')
    spec = importlib.util.spec_from_file_location('_ingress_column_scaffold_seed', path)
    if spec is None or spec.loader is None:
        raise ImportError('cannot load column scaffold seed planner')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Agent(os.path.dirname(path))


def _authorized_seed_proposal(agent, observation):
    """Use the seed planner only as a proposal source, then authorize it fresh."""
    if not observation.get('optimize') or agent._seed_planner is None:
        return None
    try:
        proposed = agent._seed_planner.policy(observation)
    except Exception:
        return None
    if not isinstance(proposed, dict):
        return None
    pool = list(observation.get('pool_list', []))
    containers = list(observation.get('container_list', []))
    try:
        pool_index = int(proposed.get('item_idx', -1))
        container_index = int(proposed.get('container_idx', -1))
        orientation = int(proposed.get('orientation', -1))
        center = np.asarray(proposed.get('place_pos'), dtype=np.float32)
    except Exception:
        return None
    if (center.shape != (3,) or not 0 <= pool_index < len(pool)
            or not 0 <= container_index < len(containers) or not 0 <= orientation < 6):
        return None
    item = pool[pool_index]
    container = containers[container_index]
    dims = orientation_dims(item, orientation)
    valid, _ = _candidate_valid(
        item,
        container,
        dims,
        center,
        _packed_boxes(container),
        _shelf_boxes(container),
        _support_surfaces(container),
    )
    if not valid:
        return None
    return {
        'item_idx': pool_index,
        'container_idx': container_index,
        'place_pos': center,
        'orientation': orientation,
    }


class Agent:
    def __init__(self, module_path: str):
        self.module_path = module_path
        self.containers = []
        self.lookahead_k = 1
        self.optimize_enabled = False
        self.offline_plan = {}
        self.offline_rank = {}
        self.offline_container_pref = {}
        self._seed_planner = None

    def get_init_states(self, init_states: dict):
        self.containers = copy.deepcopy(list(init_states.get('container_list', [])))
        self.lookahead_k = int(init_states.get('lookahead_k', 1))
        self.optimize_enabled = bool(init_states.get('optimize', False))
        self.offline_plan = {}
        self.offline_rank = {}
        self.offline_container_pref = {}
        self._seed_planner = None
        return True

    def optimize(self, item_list: list):
        self.offline_plan = {}
        self.offline_rank = {}
        self.offline_container_pref = {}
        remaining = sorted((dict(item) for item in item_list), key=_offline_static_key)
        if not remaining:
            return []
        if not self.containers:
            order = [int(item['index']) for item in remaining]
            self.offline_rank = {item_id: rank for rank, item_id in enumerate(order)}
            return order

        # The Public-29.7 planner supplies a strong heavy-rigid, low-column
        # skeleton.  Preserve that proven ordering/plan, but never trust its
        # online fallback directly: every target is re-authorized below against
        # the current observation and official float32/margin semantics.
        try:
            seed = _load_seed_planner()
            seed.get_init_states({
                'optimize': True,
                'lookahead_k': max(1, self.lookahead_k),
                'container_list': copy.deepcopy(self.containers),
            })
            order = [int(value) for value in seed.optimize(copy.deepcopy(item_list))]
            expected = [int(item['index']) for item in item_list]
            if len(order) != len(expected) or sorted(order) != sorted(expected):
                raise ValueError('seed planner did not return an exact permutation')
            self._seed_planner = seed
            self.offline_plan = {
                int(item_id): {
                    'container_idx': int(plan['container_idx']),
                    'place_pos': np.asarray(plan['place_pos'], dtype=np.float32).copy(),
                    'orientation': int(plan['orientation']),
                }
                for item_id, plan in getattr(seed, 'offline_plan', {}).items()
            }
            self.offline_rank = {item_id: rank for rank, item_id in enumerate(order)}
            self.offline_container_pref = {
                item_id: int(plan['container_idx']) for item_id, plan in self.offline_plan.items()
            }
            priority_containers = [
                index for index, container in enumerate(self.containers)
                if bool(container.get('is_prioritized', False))
            ]
            if priority_containers:
                for item in item_list:
                    item_id = int(item['index'])
                    if bool(item.get('is_prioritized', False)) and item_id not in self.offline_container_pref:
                        self.offline_container_pref[item_id] = priority_containers[0]
            return order
        except Exception:
            self._seed_planner = None
            self.offline_plan = {}
            self.offline_rank = {}
            self.offline_container_pref = {}

        virtual_containers = copy.deepcopy(self.containers)
        planned_order = []
        overall_deadline = time.perf_counter() + 110.0
        while remaining and time.perf_counter() < overall_deadline:
            step_deadline = min(overall_deadline, time.perf_counter() + min(3.0, 0.75 + 0.08*len(remaining)))
            observation = {
                'optimize': True,
                'lookahead_k': len(remaining),
                'pool_list': remaining,
                'container_list': virtual_containers,
                'depth_map': None,
            }
            candidates = _enumerate_candidates(
                observation,
                deadline=step_deadline,
                max_checks=min(22000, max(6000, len(remaining)*480)),
                per_orientation_limit=220,
            )
            chosen = _choose_candidate(candidates, remaining, virtual_containers)
            if chosen is None and time.perf_counter() < step_deadline:
                chosen = _dense_recovery(observation, deadline=step_deadline, max_checks=5000)
            if chosen is None:
                break
            pool_index = int(chosen['item_idx'])
            container_index = int(chosen['container_idx'])
            orientation = int(chosen['orientation'])
            if not (0 <= pool_index < len(remaining) and 0 <= container_index < len(virtual_containers)):
                break
            item = remaining[pool_index]
            container = virtual_containers[container_index]
            dims = orientation_dims(item, orientation)
            valid, metrics = _candidate_valid(
                item,
                container,
                dims,
                chosen['place_pos'],
                _packed_boxes(container),
                _shelf_boxes(container),
                _support_surfaces(container),
            )
            if not valid:
                break
            item_id = int(item['index'])
            action = {
                'item_idx': pool_index,
                'container_idx': container_index,
                'place_pos': np.asarray(chosen['place_pos'], dtype=np.float32),
                'orientation': orientation,
            }
            self.offline_plan[item_id] = {
                'container_idx': container_index,
                'place_pos': action['place_pos'].copy(),
                'orientation': orientation,
            }
            self.offline_container_pref[item_id] = container_index
            planned_order.append(item_id)
            _virtual_add(container, item, action, metrics)
            remaining.pop(pool_index)

        remaining.sort(key=_offline_static_key)
        planned_order.extend(int(item['index']) for item in remaining)
        self.offline_rank = {item_id: rank for rank, item_id in enumerate(planned_order)}

        priority_containers = [
            index for index, container in enumerate(self.containers)
            if bool(container.get('is_prioritized', False))
        ]
        if priority_containers:
            for item in item_list:
                item_id = int(item['index'])
                if bool(item.get('is_prioritized', False)) and item_id not in self.offline_container_pref:
                    self.offline_container_pref[item_id] = priority_containers[0]
        return planned_order

    def policy(self, observation: dict):
        # Reserve one global budget across planned-target validation, the seed
        # planner, main catalog, and both rescue stages.  Starting the clock
        # after the seed call could combine its worst case with another full
        # five-second search and cross the official eight-second timeout.
        deadline = time.perf_counter() + 5.0
        planned = _authorized_planned_action(self, observation)
        if planned is not None:
            return planned

        seed_proposal = _authorized_seed_proposal(self, observation)
        if seed_proposal is not None:
            return seed_proposal

        candidates = _enumerate_candidates(
            observation,
            deadline=deadline,
            max_checks=18000,
            per_orientation_limit=180,
        )
        if observation.get('optimize') and self.offline_rank:
            pool = list(observation.get('pool_list', []))
            for candidate in candidates:
                item_id = int(pool[int(candidate['item_idx'])].get('index', -1))
                rank = self.offline_rank.get(item_id, 10**6)
                candidate['score'] += max(0.0, 4.0 - 0.06*rank)
                preferred = self.offline_container_pref.get(item_id)
                if preferred is not None:
                    candidate['score'] += 2.0 if int(candidate['container_idx']) == int(preferred) else -0.7
            candidates.sort(key=lambda candidate: float(candidate['score']), reverse=True)

        chosen = _choose_candidate(
            candidates,
            list(observation.get('pool_list', [])),
            list(observation.get('container_list', [])),
        )
        if chosen is not None:
            return {
                'item_idx': int(chosen['item_idx']),
                'container_idx': int(chosen['container_idx']),
                'place_pos': np.asarray(chosen['place_pos'], dtype=np.float32),
                'orientation': int(chosen['orientation']),
            }
        recovery = _dense_recovery(observation, deadline=deadline, max_checks=12000)
        if recovery is not None:
            return recovery
        relaxed = _support_relaxed_recovery(observation, deadline=deadline, max_checks=16000)
        return relaxed if relaxed is not None else _contained_last_resort(observation)
