import math
import time
import copy
import numpy as np

_ORIENTATION_PERMS = (
    (0, 1, 2),
    (0, 2, 1),
    (2, 1, 0),
    (1, 0, 2),
    (1, 2, 0),
    (2, 0, 1),
)


def orientation_dims(item, orn_idx):
    dims = (float(item['length']), float(item['width']), float(item['height']))
    p = _ORIENTATION_PERMS[int(orn_idx)]
    return (dims[p[0]], dims[p[1]], dims[p[2]])


def quat_to_abs_rot(q):
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x*x + y*y + z*z + w*w)
    if n <= 1e-12:
        return np.eye(3, dtype=np.float64)
    x, y, z, w = x/n, y/n, z/n, w/n
    xx, yy, zz = x*x, y*y, z*z
    xy, xz, yz = x*y, x*z, y*z
    wx, wy, wz = w*x, w*y, w*z
    r = np.array([
        [1 - 2*(yy + zz), 2*(xy - wz),     2*(xz + wy)],
        [2*(xy + wz),     1 - 2*(xx + zz), 2*(yz - wx)],
        [2*(xz - wy),     2*(yz + wx),     1 - 2*(xx + yy)],
    ], dtype=np.float64)
    return np.abs(r)


def packed_aabb(item, container_offset_x):
    pos = item.get('pos')
    orn = item.get('orn')
    if pos is None or orn is None:
        return None
    half = np.array([
        float(item['length']) * 0.5,
        float(item['width']) * 0.5,
        float(item['height']) * 0.5,
    ], dtype=np.float64)
    aabb_half = quat_to_abs_rot(orn).dot(half)
    center = np.array([
        float(pos[0]) - float(container_offset_x),
        float(pos[1]),
        float(pos[2]),
    ], dtype=np.float64)
    return center - aabb_half, center + aabb_half


def _container_offset_x(container):
    center = container.get('center', (0.0, 0.0, 0.0))
    return float(center[0]) if center is not None else 0.0


def _local_planes(container):
    offset_x = _container_offset_x(container)
    n_vecs = np.asarray(container.get('n_vecs', []), dtype=np.float64)
    points = np.asarray(container.get('points', []), dtype=np.float64)
    if len(n_vecs) and len(points) == len(n_vecs):
        points = points.copy()
        # Real simulator plane points are world coordinates.  Some lightweight
        # tests/tools provide local points; detect that case instead of blindly
        # subtracting a multi-container X offset.
        if abs(float(np.mean(points[:, 0])) - offset_x) <= float(container.get('length', 2.0)):
            points[:, 0] -= offset_x
        return n_vecs, points
    # Conservative rectangular fallback for malformed/legacy observations.
    l = float(container['length']); w = float(container['width']); h = float(container['height'])
    t = float(container.get('thickness', 0.04))
    floor = t + 0.01
    n_vecs = np.array([
        [-1,0,0],[1,0,0],[0,-1,0],[0,1,0],[0,0,-1],[0,0,1]
    ], dtype=np.float64)
    points = np.array([
        [-l/2+t,0,0],[l/2-t,0,0],[0,-w/2+t,0],[0,w/2-t,0],[0,0,floor],[0,0,h+0.01-t]
    ], dtype=np.float64)
    return n_vecs, points


def _candidate_corners(center, dims):
    c = np.asarray(center, dtype=np.float64)
    h = np.asarray(dims, dtype=np.float64) * 0.5
    signs = np.array([
        [-1,-1,-1],[-1,-1,1],[-1,1,-1],[-1,1,1],
        [1,-1,-1],[1,-1,1],[1,1,-1],[1,1,1]
    ], dtype=np.float64)
    return c + signs * h


def _inside_container(container, center, dims, margin=-0.007):
    n_vecs, points = _local_planes(container)
    corners = _candidate_corners(center, dims)
    # Plane normals point outward: every corner must lie at or behind each plane.
    dots = (corners[:, None, :] - points[None, :, :]) * n_vecs[None, :, :]
    vals = dots.sum(axis=2)
    return bool(np.all(vals <= float(margin) + 1e-10))


def _overlaps(a_min, a_max, b_min, b_max, margin=0.001):
    a_min = np.asarray(a_min, dtype=np.float64); a_max = np.asarray(a_max, dtype=np.float64)
    b_min = np.asarray(b_min, dtype=np.float64); b_max = np.asarray(b_max, dtype=np.float64)
    m = float(margin)
    for axis in range(3):
        if a_max[axis] <= b_min[axis] + m or b_max[axis] <= a_min[axis] + m:
            return False
    return True


def _floor_z(container):
    n_vecs, points = _local_planes(container)
    best = None
    for n, p in zip(n_vecs, points):
        if n[2] < -0.9 and abs(n[0]) < 0.1 and abs(n[1]) < 0.1:
            best = float(p[2])
            break
    if best is None:
        best = float(container.get('thickness', 0.04)) + 0.01
    return best


def _shelf_boxes(container):
    l = float(container['length']); w = float(container['width']); h = float(container['height'])
    t = float(container.get('thickness', 0.04)); cut_x = float(container.get('cut_x', 0.3))
    floor = _floor_z(container)
    top = h * 0.5 + floor
    z0 = top - t
    # Small shelf is always present along the cut-corner side.
    small = (
        np.array([-l/2 + t, -w/2 + t, z0], dtype=np.float64),
        np.array([-l/2 + t + cut_x, w/2 - t, top], dtype=np.float64),
        {'kind': 'small_shelf', 'mass': 1e9, 'is_soft': False, 'is_prioritized': False},
    )
    boxes = [small]
    if bool(container.get('shelf', False)):
        main = (
            np.array([-l/2 + t, t, z0], dtype=np.float64),
            np.array([ l/2 - t, w/2 - t, top], dtype=np.float64),
            {'kind': 'main_shelf', 'mass': 1e9, 'is_soft': False, 'is_prioritized': False},
        )
        boxes.append(main)
    return boxes


def _rect_overlap_area(a_min_xy, a_max_xy, b_min_xy, b_max_xy):
    dx = max(0.0, min(float(a_max_xy[0]), float(b_max_xy[0])) - max(float(a_min_xy[0]), float(b_min_xy[0])))
    dy = max(0.0, min(float(a_max_xy[1]), float(b_max_xy[1])) - max(float(a_min_xy[1]), float(b_min_xy[1])))
    return dx * dy


def _support_ratio(container, center, dims, packed_boxes, support_tol=0.025):
    c = np.asarray(center, dtype=np.float64); d = np.asarray(dims, dtype=np.float64)
    half = d * 0.5
    bottom = float(c[2] - half[2])
    footprint_min = c[:2] - half[:2]
    footprint_max = c[:2] + half[:2]
    footprint_area = max(float(d[0] * d[1]), 1e-9)
    floor = _floor_z(container)
    if abs(bottom - floor) <= support_tol:
        return 1.0, floor

    supports = list(packed_boxes) + _shelf_boxes(container)
    area = 0.0
    support_z = -1e9
    for lo, hi, _meta in supports:
        z = float(hi[2])
        if abs(bottom - z) <= support_tol:
            ov = _rect_overlap_area(footprint_min, footprint_max, lo[:2], hi[:2])
            if ov > 0:
                area += ov
                support_z = max(support_z, z)
    return min(1.0, area / footprint_area), (support_z if support_z > -1e8 else floor)


def _transport_clear(container, center, dims, packed_boxes, shelf_boxes=None):
    """Conservative AABB approximation of PlacementValidator.check_transport_path.

    The simulator inserts at a clamped X from the front, moves along Y, then
    slides along X at the target depth.  Both swept segments must remain clear.
    """
    c = np.asarray(center, dtype=np.float64)
    d = np.asarray(dims, dtype=np.float64)
    half = d * 0.5
    shelves = _shelf_boxes(container) if shelf_boxes is None else shelf_boxes

    thickness = float(container.get('thickness', 0.04))
    height = float(container['height'])
    width = float(container['width'])
    length = float(container['length'])
    cut_x = float(container.get('cut_x', 0.0))

    bottom = float(c[2] - half[2])
    resting_surfaces = [thickness, height * 0.5 + thickness]
    lift = 0.08
    if any(0.0 <= bottom - z <= 0.05 for z in resting_surfaces):
        lift = 0.0

    # Match the validator's headroom clipping around the shelf underside and roof.
    top = float(c[2] + half[2])
    if lift > 0.0:
        for ceiling_z in (height * 0.5, height - thickness):
            clearance = ceiling_z - top
            if 0.0 <= clearance < lift + 0.018:
                lift = max(0.0, clearance - 0.018 - 0.0005)
                break
    path_z = min(height - thickness - half[2] - 0.01, float(c[2] + lift))

    start_margin = 0.01
    x_min = -length * 0.5 + thickness + cut_x + half[0] + start_margin
    x_max =  length * 0.5 - thickness - half[0] - start_margin
    if x_min <= x_max:
        start_x = min(max(float(c[0]), x_min), x_max)
    else:
        start_x = float(c[0])

    z0, z1 = path_z - half[2], path_z + half[2]
    safety = 0.016

    def sweep_hits(slo, shi):
        for lo, hi, _meta in list(packed_boxes) + list(shelves):
            separated = (
                shi[0] + safety <= lo[0] or hi[0] + safety <= slo[0] or
                shi[1] + safety <= lo[1] or hi[1] + safety <= slo[1] or
                shi[2] + safety <= lo[2] or hi[2] + safety <= slo[2]
            )
            if not separated:
                return True
        return False

    # Segment 1: from the open front to target Y at clamped insertion X.
    y_start = -width * 0.5
    seg1_lo = np.array([start_x - half[0], min(y_start, float(c[1])) - half[1], z0])
    seg1_hi = np.array([start_x + half[0], max(y_start, float(c[1])) + half[1], z1])
    if sweep_hits(seg1_lo, seg1_hi):
        return False

    # Segment 2: lateral X slide at target Y.
    seg2_lo = np.array([min(start_x, float(c[0])) - half[0], float(c[1]) - half[1], z0])
    seg2_hi = np.array([max(start_x, float(c[0])) + half[0], float(c[1]) + half[1], z1])
    if sweep_hits(seg2_lo, seg2_hi):
        return False
    return True


def _center_bounds(container, dims, z, margin=-0.008):
    n_vecs, points = _local_planes(container)
    half = np.asarray(dims, dtype=np.float64) * 0.5
    l = float(container['length']); w = float(container['width'])
    t = float(container.get('thickness', 0.04))
    x_lo, x_hi = -l/2 + t + half[0], l/2 - t - half[0]
    y_lo, y_hi = -w/2 + t + half[1], w/2 - t - half[1]
    for n, point in zip(n_vecs, points):
        rhs = float(np.dot(n, point) + margin - np.dot(np.abs(n), half))
        # Container cross-section planes are X/Z only.
        if abs(n[0]) > 1e-9 and abs(n[1]) < 1e-9:
            v = (rhs - float(n[2]) * float(z)) / float(n[0])
            if n[0] > 0:
                x_hi = min(x_hi, v)
            else:
                x_lo = max(x_lo, v)
        # Front/back planes are Y only.
        if abs(n[1]) > 1e-9 and abs(n[0]) < 1e-9 and abs(n[2]) < 1e-9:
            v = rhs / float(n[1])
            if n[1] > 0:
                y_hi = min(y_hi, v)
            else:
                y_lo = max(y_lo, v)
    if x_lo > x_hi or y_lo > y_hi:
        return None
    return float(x_lo), float(x_hi), float(y_lo), float(y_hi)


def _candidate_points(container, dims, packed_boxes, max_points=300):
    d = np.asarray(dims, dtype=np.float64)
    half = d * 0.5
    floor = _floor_z(container)
    floor_gap = 0.008
    stack_gap = 0.006
    shelf_gap = 0.018
    shelves = _shelf_boxes(container)

    priority_points = []
    general_points = []
    seen = set()

    def add_point(target, x, y, z):
        bounds = _center_bounds(container, dims, z)
        if bounds is None:
            return
        x_lo, x_hi, y_lo, y_hi = bounds
        if x < x_lo - 1e-8 or x > x_hi + 1e-8 or y < y_lo - 1e-8 or y > y_hi + 1e-8:
            return
        key = (round(float(x), 4), round(float(y), 4), round(float(z), 4))
        if key in seen:
            return
        pt = (float(x), float(y), float(z))
        if not _inside_container(container, pt, dims, -0.007):
            return
        seen.add(key)
        target.append(pt)

    # Always preserve floor/back extreme points.
    floor_z = floor + floor_gap + half[2]
    bounds = _center_bounds(container, dims, floor_z)
    if bounds is not None:
        x_lo, x_hi, y_lo, y_hi = bounds
        x_mid = min(max(0.0, x_lo), x_hi)
        for x, y in [
            (x_lo, y_hi), (x_hi, y_hi), (x_mid, y_hi),
            (x_lo, y_lo), (x_hi, y_lo), (x_mid, y_lo),
        ]:
            add_point(priority_points, x, y, floor_z)

    # Every real support gets a reserved set of candidates.  Clipping the
    # support rectangle to legal center bounds creates placements that can slide
    # across a top surface, which is essential once the simple skyline is full.
    supports = list(packed_boxes) + list(shelves)
    supports.sort(key=lambda b: (float(b[1][2]), float(b[0][1]), float(b[0][0])))
    for lo, hi, meta in supports:
        is_shelf = bool(meta.get('kind')) if isinstance(meta, dict) else False
        gap = shelf_gap if is_shelf else stack_gap
        z = float(hi[2]) + gap + half[2]
        bounds = _center_bounds(container, dims, z)
        if bounds is None:
            continue
        x_lo, x_hi, y_lo, y_hi = bounds
        sx0 = max(x_lo, float(lo[0])); sx1 = min(x_hi, float(hi[0]))
        sy0 = max(y_lo, float(lo[1])); sy1 = min(y_hi, float(hi[1]))
        if sx0 <= sx1 and sy0 <= sy1:
            # Sample a compact 3x3 grid on every support.  Corners + center alone
            # miss many late-stage placements where only one edge of a broad top
            # remains reachable through the insertion corridor.
            xs = (sx0, (sx0 + sx1) * 0.5, sx1)
            ys = (sy0, (sy0 + sy1) * 0.5, sy1)
            for y in ys:
                for x in xs:
                    add_point(priority_points, x, y, z)

    # General skyline/extreme-point candidates fill the remaining budget.
    levels = [floor_z]
    levels += [float(hi[2]) + stack_gap + half[2] for _lo, hi, _meta in packed_boxes]
    levels += [float(hi[2]) + shelf_gap + half[2] for _lo, hi, _meta in shelves]
    levels = sorted({round(float(z), 5) for z in levels})

    for z in levels:
        bounds = _center_bounds(container, dims, z)
        if bounds is None:
            continue
        x_lo, x_hi, y_lo, y_hi = bounds
        x_mid = min(max(0.0, x_lo), x_hi)
        base = [(x_lo, y_hi, z), (x_hi, y_hi, z), (x_mid, y_hi, z)]

        z0, z1 = z - half[2], z + half[2]
        near = []
        for box in packed_boxes:
            lo, hi, _meta = box
            if not (z1 < lo[2] - 0.04 or hi[2] < z0 - 0.04):
                near.append(box)
        near.sort(key=lambda b: (-float(b[1][1]), float(b[1][2])))
        near = near[:8]
        for lo, hi, _meta in near:
            x_left = float(lo[0] - half[0] - 0.018)
            x_right = float(hi[0] + half[0] + 0.018)
            y_front = float(lo[1] - half[1] - 0.018)
            box_x = float((lo[0] + hi[0]) * 0.5)
            box_y = float((lo[1] + hi[1]) * 0.5)
            base.extend([
                (x_left, y_hi, z), (x_right, y_hi, z),
                (box_x, y_front, z), (x_lo, y_front, z), (x_hi, y_front, z),
            ])
            bottom = z - half[2]
            if abs(bottom - float(hi[2])) <= 0.03:
                base.append((box_x, box_y, z))

        for x, y, zz in base:
            add_point(general_points, x, y, zz)

    # Keep reserved support points even when many low skyline levels exist.
    if len(priority_points) >= max_points:
        return priority_points[:max_points]
    remaining = max_points - len(priority_points)
    general_points.sort(key=lambda p: (p[2], -p[1], abs(p[0])))
    return priority_points + general_points[:remaining]


def _score_candidate(item, container, dims, center, support_ratio, support_z, packed_items, all_containers):
    l, w, h = (float(v) for v in dims)
    x, y, z = (float(v) for v in center)
    floor = _floor_z(container)
    ch = max(float(container['height']), 1e-6)
    cw = max(float(container['width']), 1e-6)
    z_norm = max(0.0, min(1.5, (z - floor) / ch))
    backness = max(0.0, min(1.0, (y + cw * 0.5) / cw))
    mass = float(item.get('mass', 1.0))
    volume = l * w * h
    cvol = float(container.get('volume', float(container['length']) * cw * ch))
    soft = bool(item.get('is_soft', False))
    priority = bool(item.get('is_prioritized', False))

    # Core packing/stability terms.
    score = 9.0 * float(support_ratio)
    score += 120.0 * volume / max(cvol, 1e-6)  # large/hard-to-place items get urgency
    score -= (4.0 + 0.28 * mass) * z_norm
    base_area = max(l * w, 1e-8)
    squat = min(4.0, base_area / max(h * h, 1e-8)) / 4.0
    score += 2.0 * squat

    # Back-first for rigid cargo preserves the insertion corridor; soft/priority
    # cargo is mildly biased toward the front/top for accessibility/protection.
    if soft or priority:
        score += 1.5 * (1.0 - backness)
        score += 2.5 * z_norm
    else:
        score += 3.0 * backness

    priority_containers = [c for c in all_containers if bool(c.get('is_prioritized', False))]
    if priority_containers:
        if priority:
            score += 28.0 if bool(container.get('is_prioritized', False)) else -30.0
        elif bool(container.get('is_prioritized', False)):
            score -= 7.0

    # Mild load balancing so two ordinary containers do not strand all remaining
    # space in one badly shaped cavity.
    used = 0.0
    for p in container.get('packed_items', []):
        used += float(p.get('length', 0.0)) * float(p.get('width', 0.0)) * float(p.get('height', 0.0))
    score += 1.5 * max(0.0, 1.0 - used / max(cvol, 1e-6))

    # Hidden placement rules: a new item may not bury a priority/soft supporter
    # unless the new item has the same attribute. Penalize by supported area.
    half = np.asarray(dims, dtype=np.float64) * 0.5
    cxy = np.asarray([x, y], dtype=np.float64)
    fmin, fmax = cxy - half[:2], cxy + half[:2]
    footprint = max(l * w, 1e-8)
    offset = _container_offset_x(container)
    bottom = z - half[2]
    for p in packed_items:
        box = packed_aabb(p, offset)
        if box is None:
            continue
        lo, hi = box
        if abs(bottom - float(hi[2])) > 0.035:
            continue
        area = _rect_overlap_area(fmin, fmax, lo[:2], hi[:2])
        if area <= 0:
            continue
        frac = min(1.0, area / footprint)
        if bool(p.get('is_soft', False)) and not soft:
            score -= 24.0 * frac
        if bool(p.get('is_prioritized', False)) and not priority:
            score -= 22.0 * frac
        pmass = float(p.get('mass', mass))
        if mass > pmass * 1.35 and pmass < 1e8:
            score -= 4.0 * frac

    return float(score)


def _packed_boxes_for_container(container):
    offset = _container_offset_x(container)
    boxes = []
    for item in container.get('packed_items', []):
        box = packed_aabb(item, offset)
        if box is not None:
            boxes.append((box[0], box[1], item))
    return boxes


def _target_clear(center, dims, packed_boxes, shelf_boxes):
    c = np.asarray(center, dtype=np.float64)
    half = np.asarray(dims, dtype=np.float64) * 0.5
    lo, hi = c - half, c + half
    for blo, bhi, _meta in list(packed_boxes) + list(shelf_boxes):
        if _overlaps(lo, hi, blo, bhi, 0.001):
            return False
    return True


def _center_supported(container, center, dims, packed_boxes):
    c = np.asarray(center, dtype=np.float64); half = np.asarray(dims, dtype=np.float64) * 0.5
    bottom = float(c[2] - half[2])
    if abs(bottom - _floor_z(container)) <= 0.03:
        return True
    for lo, hi, _meta in list(packed_boxes) + _shelf_boxes(container):
        if abs(bottom - float(hi[2])) > 0.03:
            continue
        if lo[0] - 0.005 <= c[0] <= hi[0] + 0.005 and lo[1] - 0.005 <= c[1] <= hi[1] + 0.005:
            return True
    return False


def _unique_orientations(item):
    seen = set()
    out = []
    for orn in range(6):
        dims = orientation_dims(item, orn)
        key = tuple(round(v, 6) for v in dims)
        if key in seen:
            continue
        seen.add(key)
        out.append((orn, dims))
    out.sort(key=lambda od: (od[1][2], -(od[1][0] * od[1][1]), od[1][1], od[0]))
    return out


def _item_urgency(item):
    l = float(item['length']); w = float(item['width']); h = float(item['height'])
    volume = l*w*h
    mass = float(item.get('mass', 1.0))
    urgency = 40.0 * volume + 0.04 * mass + 0.30 * max(l, w, h)
    if bool(item.get('is_soft', False)):
        urgency -= 1.2
    if bool(item.get('is_prioritized', False)):
        urgency -= 0.25
    return urgency


def _candidate_is_acceptable(item, container, dims, center, packed_boxes, shelves):
    if not _inside_container(container, center, dims, -0.007):
        return False, 0.0, _floor_z(container)
    if not _target_clear(center, dims, packed_boxes, shelves):
        return False, 0.0, _floor_z(container)
    support_ratio, support_z = _support_ratio(container, center, dims, packed_boxes)
    mass = float(item.get('mass', 1.0))
    threshold = 0.72 if mass >= 12.0 else 0.62
    if bool(item.get('is_soft', False)):
        threshold = max(threshold, 0.70)
    if support_ratio < threshold or not _center_supported(container, center, dims, packed_boxes):
        return False, support_ratio, support_z
    if not _transport_clear(container, center, dims, packed_boxes, shelves):
        return False, support_ratio, support_z
    return True, support_ratio, support_z


def _best_action(observation):
    pool = list(observation.get('pool_list', []))
    containers = list(observation.get('container_list', []))
    if not pool or not containers:
        return None

    ranked = sorted(enumerate(pool), key=lambda kv: (-_item_urgency(kv[1]), kv[0]))
    selected = ranked[:10]
    selected_ids = {i for i, _ in selected}
    # Ensure special-attribute cargo is not starved forever in large lookahead pools.
    for i, item in ranked[10:]:
        if len(selected) >= 12:
            break
        if (item.get('is_prioritized') or item.get('is_soft')) and i not in selected_ids:
            selected.append((i, item)); selected_ids.add(i)

    best = None
    best_key = None
    max_candidate_checks = int(observation.get('_max_candidate_checks', 6500))
    candidate_point_limit = int(observation.get('_candidate_point_limit', 300))
    candidate_checks = 0
    for pool_idx, item in selected:
        container_order = list(enumerate(containers))
        if item.get('is_prioritized') and any(c.get('is_prioritized') for c in containers):
            container_order.sort(key=lambda ci: (not bool(ci[1].get('is_prioritized', False)), ci[0]))
        for container_idx, container in container_order:
            packed_boxes = _packed_boxes_for_container(container)
            shelves = _shelf_boxes(container)
            for orn, dims in _unique_orientations(item):
                # Rough dimension pruning before candidate construction.
                if dims[0] > float(container['length']) + 1e-6 or dims[1] > float(container['width']) + 1e-6 or dims[2] > float(container['height']) + 1e-6:
                    continue
                points = _candidate_points(container, dims, packed_boxes, max_points=candidate_point_limit)
                for center in points:
                    if candidate_checks >= max_candidate_checks:
                        return best
                    candidate_checks += 1
                    ok, support_ratio, support_z = _candidate_is_acceptable(item, container, dims, center, packed_boxes, shelves)
                    if not ok:
                        continue
                    score = _score_candidate(
                        item, container, dims, center, support_ratio, support_z,
                        container.get('packed_items', []), containers,
                    )
                    # Deterministic tie break: low Z, deep Y, stable orientation, pool order.
                    tie = (score, -center[2], center[1], -abs(center[0]), -orn, -pool_idx, -container_idx)
                    if best_key is None or tie > best_key:
                        best_key = tie
                        best = {
                            'item_idx': int(pool_idx),
                            'container_idx': int(container_idx),
                            'place_pos': np.asarray(center, dtype=np.float32),
                            'orientation': int(orn),
                        }
    return best


def _fallback_action(observation):
    pool = list(observation.get('pool_list', []))
    containers = list(observation.get('container_list', []))
    if not pool or not containers:
        return {
            'item_idx': 0, 'container_idx': 0,
            'place_pos': np.array([0.0, 0.0, 0.1], dtype=np.float32),
            'orientation': 0,
        }

    def deterministic_default():
        pool_idx, item = min(
            enumerate(pool),
            key=lambda kv: (
                float(kv[1]['length']) * float(kv[1]['width']) * float(kv[1]['height']),
                kv[0],
            ),
        )
        container_idx = 0
        if item.get('is_prioritized'):
            for i, c in enumerate(containers):
                if c.get('is_prioritized'):
                    container_idx = i
                    break
        container = containers[container_idx]
        orn, dims = _unique_orientations(item)[0]
        floor = _floor_z(container)
        z = floor + 0.012 + dims[2] * 0.5
        bounds = _center_bounds(container, dims, z)
        if bounds is None:
            pos = (0.0, 0.0, max(0.05, z))
        else:
            xlo, xhi, _ylo, yhi = bounds
            pos = (min(max(0.0, xlo), xhi), yhi, z)
        return {
            'item_idx': int(pool_idx), 'container_idx': int(container_idx),
            'place_pos': np.asarray(pos, dtype=np.float32), 'orientation': int(orn),
        }

    # A bounded dense search catches holes missed by the fast extreme-point pass.
    # A hard candidate budget prevents the official 8 s policy timeout from being
    # consumed by an impossible late-stage scene.
    max_checks = 2600
    checks = 0

    # Recovery mode: when the optimized extreme-point search cannot place any
    # preferred item, try the easiest/smallest visible cargo first.  Completing
    # the episode is worth more than insisting on the large-item ordering here.
    def recovery_key(kv):
        idx, it = kv
        l = float(it['length']); w = float(it['width']); h = float(it['height'])
        return (l*w*h, max(l, w, h), float(it.get('mass', 1.0)), idx)

    ranked = sorted(enumerate(pool), key=recovery_key)
    for pool_idx, item in ranked:
        c_order = list(enumerate(containers))
        if item.get('is_prioritized') and any(c.get('is_prioritized') for c in containers):
            c_order.sort(key=lambda ci: (not bool(ci[1].get('is_prioritized', False)), ci[0]))
        for container_idx, container in c_order:
            packed = _packed_boxes_for_container(container)
            shelves = _shelf_boxes(container)
            for orn, dims in _unique_orientations(item):
                half = np.asarray(dims) * 0.5
                levels = [_floor_z(container) + 0.008 + half[2]]
                levels += [float(hi[2]) + 0.006 + half[2] for _lo, hi, _meta in packed]
                levels += [float(hi[2]) + 0.018 + half[2] for _lo, hi, _meta in shelves]
                for z in sorted({round(v, 5) for v in levels}):
                    bounds = _center_bounds(container, dims, z)
                    if bounds is None:
                        continue
                    xlo, xhi, ylo, yhi = bounds
                    for y in np.linspace(yhi, ylo, 11):
                        for x in np.linspace(xlo, xhi, 11):
                            if checks >= max_checks:
                                return deterministic_default()
                            checks += 1
                            center = (float(x), float(y), float(z))
                            ok, _, _ = _candidate_is_acceptable(
                                item, container, dims, center, packed, shelves
                            )
                            if ok:
                                return {
                                    'item_idx': int(pool_idx), 'container_idx': int(container_idx),
                                    'place_pos': np.asarray(center, dtype=np.float32), 'orientation': int(orn),
                                }

    return deterministic_default()


def _static_order_key(item):
    l = float(item['length'])
    w = float(item['width'])
    h = float(item['height'])
    volume = l * w * h
    footprint = max(l*w, l*h, w*h)
    mass = float(item.get('mass', 1.0))
    soft = bool(item.get('is_soft', False))
    priority = bool(item.get('is_prioritized', False))
    group = 2 if soft else (1 if priority else 0)
    return (group, -mass, -footprint, -volume, -max(l, w, h), int(item['index']))


def _orientation_quat(orn_idx):
    half_pi = math.pi * 0.5
    eulers = (
        (0.0, 0.0, 0.0),
        (half_pi, 0.0, 0.0),
        (0.0, half_pi, 0.0),
        (0.0, 0.0, half_pi),
        (0.0, half_pi, half_pi),
        (half_pi, 0.0, half_pi),
    )
    roll, pitch, yaw = eulers[int(orn_idx)]
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    return (
        sr*cp*cy - cr*sp*sy,
        cr*sp*cy + sr*cp*sy,
        cr*cp*sy - sr*sp*cy,
        cr*cp*cy + sr*sp*sy,
    )


def _virtual_add_item(container, item, action):
    placed = dict(item)
    center = np.asarray(action['place_pos'], dtype=np.float64)
    offset_x = _container_offset_x(container)
    placed['pos'] = (float(center[0] + offset_x), float(center[1]), float(center[2]))
    placed['orn'] = _orientation_quat(int(action['orientation']))
    placed['belongs_to'] = int(container.get('index', 0))
    container.setdefault('packed_items', []).append(placed)


class HistoricalSeed:
    def __init__(self, module_path: str):
        self.module_path = module_path
        self.containers = []
        self.lookahead_k = 1
        self.optimize_enabled = False
        self.offline_plan = {}
        self.offline_rank = {}

    def get_init_states(self, init_states: dict):
        self.containers = list(init_states.get('container_list', []))
        self.lookahead_k = int(init_states.get('lookahead_k', 1))
        self.optimize_enabled = bool(init_states.get('optimize', False))
        self.offline_plan = {}
        self.offline_rank = {}
        return True

    def optimize(self, item_list: list):
        # Task A exposes the complete stream and allows a much larger time budget.
        # Use the same conservative geometry as the online policy to build a
        # virtual packing prefix, then append any unresolved items with a stable
        # heavy/rigid-first order.  The virtual prefix adapts to container shape
        # instead of relying on a size-only sort.
        self.offline_plan = {}
        self.offline_rank = {}
        remaining = [dict(item) for item in item_list]
        if not remaining:
            return []
        if not self.containers:
            return [int(item['index']) for item in sorted(remaining, key=_static_order_key)]

        virtual_containers = copy.deepcopy(self.containers)
        planned = []
        started = time.perf_counter()
        planning_budget = 55.0  # comfortably below the official 180 s timeout

        while remaining and (time.perf_counter() - started) < planning_budget:
            obs = {
                'optimize': True,
                'lookahead_k': len(remaining),
                'pool_list': remaining,
                'container_list': virtual_containers,
                '_max_candidate_checks': 4200,
                '_candidate_point_limit': 220,
            }
            action = _best_action(obs)
            if action is None:
                action = _fallback_action(obs)
            pool_idx = int(action.get('item_idx', -1))
            container_idx = int(action.get('container_idx', -1))
            if not (0 <= pool_idx < len(remaining) and 0 <= container_idx < len(virtual_containers)):
                break
            item = remaining[pool_idx]
            container = virtual_containers[container_idx]
            orn = int(action.get('orientation', -1))
            if not (0 <= orn < 6):
                break
            center = tuple(float(v) for v in action['place_pos'])
            dims = orientation_dims(item, orn)
            packed = _packed_boxes_for_container(container)
            shelves = _shelf_boxes(container)
            ok, _sr, _sz = _candidate_is_acceptable(item, container, dims, center, packed, shelves)
            if not ok:
                break
            _virtual_add_item(container, item, action)
            item_id = int(item['index'])
            self.offline_plan[item_id] = {
                'container_idx': int(container_idx),
                'place_pos': np.asarray(action['place_pos'], dtype=np.float32).copy(),
                'orientation': int(action['orientation']),
            }
            self.offline_rank[item_id] = len(planned)
            planned.append(item_id)
            remaining.pop(pool_idx)

        remaining.sort(key=_static_order_key)
        planned.extend(int(item['index']) for item in remaining)
        return planned

    def policy(self, observation: dict):
        # In Task A the same agent instance receives optimize() then policy().
        # Reuse a virtual-plan target when it still matches the real observed
        # geometry; physical settling can invalidate it, in which case fall back
        # to the normal online search.
        if observation.get('optimize') and self.offline_plan:
            pool = list(observation.get('pool_list', []))
            containers = list(observation.get('container_list', []))
            candidates = []
            for pool_idx, item in enumerate(pool):
                item_id = int(item.get('index', -1))
                plan = self.offline_plan.get(item_id)
                if plan is not None:
                    candidates.append((self.offline_rank.get(item_id, 10**9), pool_idx, item, plan))
            candidates.sort(key=lambda x: (x[0], x[1]))
            for _rank, pool_idx, item, plan in candidates:
                container_idx = int(plan['container_idx'])
                orn = int(plan['orientation'])
                if not (0 <= container_idx < len(containers) and 0 <= orn < 6):
                    continue
                container = containers[container_idx]
                center = tuple(float(v) for v in plan['place_pos'])
                dims = orientation_dims(item, orn)
                packed = _packed_boxes_for_container(container)
                shelves = _shelf_boxes(container)
                ok, _support_ratio_value, _support_z_value = _candidate_is_acceptable(
                    item, container, dims, center, packed, shelves
                )
                if ok:
                    return {
                        'item_idx': int(pool_idx),
                        'container_idx': container_idx,
                        'place_pos': np.asarray(center, dtype=np.float32),
                        'orientation': orn,
                    }

        action = _best_action(observation)
        if action is None:
            action = _fallback_action(observation)
        return action




class HistoricalSeedError(RuntimeError):
    """Typed fail-closed diagnostic for a missing historical candidate."""


def historical_source_descriptor() -> dict[str, object]:
    """Return provenance without consulting any external artifact at runtime."""
    return {
        "algorithm": "conservative_extreme_point_packing_historical_control",
        "adaptation": "standalone historical virtual-plan seed",
        "runtime_artifact_dependency": False,
        "runtime_result_dependency": False,
    }
