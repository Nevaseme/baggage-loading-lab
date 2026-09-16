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
    p = _ORIENTATION_PERMS[int(orientation)]
    return dims[p[0]], dims[p[1]], dims[p[2]]


def _container_offset_x(container):
    center = container.get('center', (0.0, 0.0, 0.0))
    if center is None:
        return 0.0
    return float(center[0])


def _local_planes(container):
    n_vecs = np.asarray(container.get('n_vecs', []), dtype=np.float64)
    points = np.asarray(container.get('points', []), dtype=np.float64)
    if len(n_vecs) and len(points) == len(n_vecs):
        points = points.copy()
        points[:, 0] -= _container_offset_x(container)
        return n_vecs, points
    l = float(container['length'])
    w = float(container['width'])
    h = float(container['height'])
    t = float(container.get('thickness', 0.04))
    n_vecs = np.asarray([
        (-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)
    ], dtype=np.float64)
    points = np.asarray([
        (-l/2+t, 0, 0), (l/2-t, 0, 0), (0, -w/2+t, 0), (0, w/2-t, 0),
        (0, 0, t), (0, 0, h-t),
    ], dtype=np.float64)
    return n_vecs, points


def inside_container(container, center, dims, margin=-0.005):
    n_vecs, points = _local_planes(container)
    center = np.asarray(center, dtype=np.float64)
    half = np.asarray(dims, dtype=np.float64) * 0.5
    dots = (n_vecs * (center - points)).sum(axis=1) + np.abs(n_vecs).dot(half)
    return bool(np.all(dots <= float(margin) + 1e-12))


def _quat_abs_rotation(q):
    x, y, z, w = (float(v) for v in q)
    norm = math.sqrt(x*x + y*y + z*z + w*w)
    if norm <= 1e-12:
        return np.eye(3, dtype=np.float64)
    x, y, z, w = x/norm, y/norm, z/norm, w/norm
    xx, yy, zz = x*x, y*y, z*z
    xy, xz, yz = x*y, x*z, y*z
    wx, wy, wz = w*x, w*y, w*z
    rot = np.asarray([
        (1 - 2*(yy+zz), 2*(xy-wz), 2*(xz+wy)),
        (2*(xy+wz), 1 - 2*(xx+zz), 2*(yz-wx)),
        (2*(xz-wy), 2*(yz+wx), 1 - 2*(xx+yy)),
    ], dtype=np.float64)
    return np.abs(rot)


def packed_item_aabb(item, container_offset_x):
    pos = item.get('pos')
    orn = item.get('orn')
    if pos is None or orn is None:
        raise ValueError('packed item requires pos and orn')
    half = np.asarray([
        float(item['length'])/2,
        float(item['width'])/2,
        float(item['height'])/2,
    ], dtype=np.float64)
    aabb_half = _quat_abs_rotation(orn).dot(half)
    center = np.asarray((float(pos[0])-float(container_offset_x), float(pos[1]), float(pos[2])), dtype=np.float64)
    return center - aabb_half, center + aabb_half


def _inner_xy_bounds(container):
    n_vecs, points = _local_planes(container)
    x_min = -float(container['length'])/2 + float(container.get('thickness', 0.04))
    x_max = float(container['length'])/2 - float(container.get('thickness', 0.04))
    y_min = -float(container['width'])/2 + float(container.get('thickness', 0.04))
    y_max = float(container['width'])/2 - float(container.get('thickness', 0.04))
    for n, p in zip(n_vecs, points):
        if n[0] < -0.9 and abs(n[1]) < 0.1 and abs(n[2]) < 0.1:
            x_min = max(x_min, float(p[0]))
        elif n[0] > 0.9 and abs(n[1]) < 0.1 and abs(n[2]) < 0.1:
            x_max = min(x_max, float(p[0]))
        elif n[1] < -0.9 and abs(n[0]) < 0.1 and abs(n[2]) < 0.1:
            y_min = max(y_min, float(p[1]))
        elif n[1] > 0.9 and abs(n[0]) < 0.1 and abs(n[2]) < 0.1:
            y_max = min(y_max, float(p[1]))
    return x_min, x_max, y_min, y_max


def _floor_z(container):
    n_vecs, points = _local_planes(container)
    for n, p in zip(n_vecs, points):
        if n[2] < -0.9 and abs(n[0]) < 0.1 and abs(n[1]) < 0.1:
            return float(p[2])
    return float(container.get('thickness', 0.04))


def reconstruct_supports(container):
    """Rebuild horizontal support rectangles from the current real observation."""
    x0, x1, y0, y1 = _inner_xy_bounds(container)
    supports = [{
        'rect': (x0, x1, y0, y1),
        'z': _floor_z(container),
        'kind': 'floor',
        'meta': {'mass': 1e12, 'is_soft': False, 'is_prioritized': False},
    }]

    l = float(container['length'])
    w = float(container['width'])
    h = float(container['height'])
    t = float(container.get('thickness', 0.04))
    cut_x = float(container.get('cut_x', 0.0))
    buffer = float(container.get('buffer', 0.01))
    shelf_top = h/2 + t + buffer

    if cut_x > 1e-9:
        supports.append({
            'rect': (-l/2+t, -l/2+t+cut_x, -w/2+t, w/2-t),
            'z': shelf_top,
            'kind': 'small_shelf',
            'meta': {'mass': 1e12, 'is_soft': False, 'is_prioritized': False},
        })
    if bool(container.get('shelf', False)):
        supports.append({
            'rect': (-l/2+t/2, l/2-t/2, t, w/2-t),
            'z': shelf_top,
            'kind': 'shelf',
            'meta': {'mass': 1e12, 'is_soft': False, 'is_prioritized': False},
        })

    offset_x = _container_offset_x(container)
    for item in container.get('packed_items', []):
        if item.get('pos') is None or item.get('orn') is None:
            continue
        lo, hi = packed_item_aabb(item, offset_x)
        supports.append({
            'rect': (float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1])),
            'z': float(hi[2]),
            'kind': 'item',
            'meta': item,
        })
    return supports


def _rect_intersection(a, b):
    x0 = max(float(a[0]), float(b[0]))
    x1 = min(float(a[1]), float(b[1]))
    y0 = max(float(a[2]), float(b[2]))
    y1 = min(float(a[3]), float(b[3]))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, x1, y0, y1)


def _rect_union_area(rects):
    if not rects:
        return 0.0
    xs = sorted({float(r[0]) for r in rects} | {float(r[1]) for r in rects})
    area = 0.0
    for xa, xb in zip(xs[:-1], xs[1:]):
        if xb <= xa:
            continue
        intervals = []
        mid = 0.5 * (xa + xb)
        for r in rects:
            if r[0] <= mid <= r[1]:
                intervals.append((float(r[2]), float(r[3])))
        if not intervals:
            continue
        intervals.sort()
        merged = 0.0
        s, e = intervals[0]
        for ns, ne in intervals[1:]:
            if ns <= e:
                e = max(e, ne)
            else:
                merged += e - s
                s, e = ns, ne
        merged += e - s
        area += (xb - xa) * merged
    return area


def support_metrics(center, dims, supports, z_tol=0.025):
    c = np.asarray(center, dtype=np.float64)
    dx, dy, dz = (float(v) for v in dims)
    bottom = float(c[2] - dz/2)
    footprint = (c[0]-dx/2, c[0]+dx/2, c[1]-dy/2, c[1]+dy/2)
    intersections = []
    supporters = []
    center_ok = False
    for s in supports:
        if abs(float(s['z']) - bottom) > z_tol:
            continue
        inter = _rect_intersection(footprint, s['rect'])
        if inter is None:
            continue
        intersections.append(inter)
        supporters.append(s)
        r = s['rect']
        if r[0]-1e-9 <= c[0] <= r[1]+1e-9 and r[2]-1e-9 <= c[1] <= r[3]+1e-9:
            center_ok = True
    area = _rect_union_area(intersections)
    ratio = min(1.0, area / max(dx*dy, 1e-12))
    supporters.sort(key=lambda s: (0 if s['kind'] == 'item' else 1, -float(s['z'])))
    return ratio, center_ok, supporters


def surface_candidate_centers(container, dims, supports, packed_boxes, max_candidates=420):
    """Generate placement centers with a fair budget across all support surfaces.

    A global early-stop over floor anchors starves upper item/shelf surfaces late in
    an episode.  Build a small ordered list per support, then round-robin them so
    every viable support receives search budget before any one surface monopolises
    it.
    """
    dx, dy, dz = (float(v) for v in dims)
    support_lists = []

    for support in sorted(supports, key=lambda s: (float(s['z']), s['kind'] != 'floor')):
        x0, x1, y0, y1 = (float(v) for v in support['rect'])
        kind = support['kind']

        if kind == 'item':
            # Real luggage tops may support a slightly wider next item as long as
            # its COM remains over the support polygon.  Requiring the entire
            # footprint to fit would make same-size and 80%-overlap stacks
            # impossible after the mandatory settling gaps.
            if x1-x0 < 0.45*dx or y1-y0 < 0.45*dy:
                continue
            xmid, ymid = 0.5*(x0+x1), 0.5*(y0+y1)
            xs = [xmid, x0+dx/2, x1-dx/2]
            ys = [y1-dy/2, y0+dy/2, ymid]
            x_allow = (x0-dx/2, x1+dx/2)
            y_allow = (y0-dy/2, y1+dy/2)
        else:
            # Floor/shelf boundaries are hard geometry; keep a small safety inset.
            if x1-x0 + 1e-9 < dx or y1-y0 + 1e-9 < dy:
                continue
            inset = 0.008 if kind == 'floor' else 0.004
            xlo, xhi = x0 + dx/2 + inset, x1 - dx/2 - inset
            ylo, yhi = y0 + dy/2 + inset, y1 - dy/2 - inset
            if xlo > xhi + 1e-9 or ylo > yhi + 1e-9:
                continue
            xs = [xlo, xhi, 0.5*(xlo+xhi)]
            ys = [yhi, ylo, 0.5*(ylo+yhi)]
            x_allow = (xlo, xhi)
            y_allow = (ylo, yhi)

        # Only hard floor/shelf surfaces need neighbour-edge anchors.  Item-top
        # supports already contribute their own centre/edge anchors; combining
        # every support with every packed box is O(n^2) and breaches the 8 s
        # policy limit late in an episode.
        if kind != 'item':
            nearby = [b for b in packed_boxes if abs(float(b[0][2]) - float(support['z'])) <= 0.09]
            nearby.sort(key=lambda b: (-float(b[1][1]), abs(float((b[0][0]+b[1][0])*0.5))))
            for blo, bhi, _meta in nearby[:10]:
                xs.extend([float(blo[0]) - dx/2, float(bhi[0]) + dx/2,
                           float(blo[0]) + dx/2, float(bhi[0]) - dx/2])
                ys.extend([float(blo[1]) - dy/2, float(bhi[1]) + dy/2,
                           float(blo[1]) + dy/2, float(bhi[1]) - dy/2])

        xs = [x for x in xs if x_allow[0]-1e-9 <= x <= x_allow[1]+1e-9]
        ys = [y for y in ys if y_allow[0]-1e-9 <= y <= y_allow[1]+1e-9]
        # Wall/support-edge flush first in X, deepest/back-most first in Y.
        xs = sorted(set(round(x, 6) for x in xs), key=lambda x: (abs(x), x))
        ys = sorted(set(round(y, 6) for y in ys), reverse=True)
        gap = 0.018 if kind in ('shelf', 'small_shelf') else (0.008 if kind == 'floor' else 0.006)
        z = float(support['z']) + gap + dz/2

        local = []
        local_seen = set()
        for y in ys:
            for x in xs:
                pt = (float(x), float(y), float(z))
                key = tuple(round(v, 5) for v in pt)
                if key in local_seen:
                    continue
                if inside_container(container, pt, dims, margin=-0.006):
                    local_seen.add(key)
                    local.append(pt)
        if local:
            support_lists.append(local)

    if not support_lists or max_candidates <= 0:
        return []

    out = []
    global_seen = set()
    depth = 0
    while len(out) < max_candidates:
        added = False
        for local in support_lists:
            if depth >= len(local):
                continue
            pt = local[depth]
            key = tuple(round(v, 5) for v in pt)
            if key not in global_seen:
                global_seen.add(key)
                out.append(pt)
                if len(out) >= max_candidates:
                    break
            added = True
        if not added:
            break
        depth += 1
    return out


def _extreme_candidate_centers(container, dims, packed_boxes, max_candidates=300):
    """Late-stage side-loading extreme points used only by rescue search."""
    dx, dy, dz = (float(v) for v in dims)
    half = np.asarray((dx, dy, dz), dtype=np.float64) * 0.5
    x_min, x_max, y_min, y_max = _inner_xy_bounds(container)
    floor_z = _floor_z(container) + 0.008 + half[2]
    shelves = _shelf_collision_boxes(container)
    levels = [floor_z]
    levels.extend(float(hi[2]) + 0.006 + half[2] for lo, hi, meta in packed_boxes)
    levels.extend(float(hi[2]) + 0.018 + half[2] for lo, hi, meta in shelves)
    levels = sorted(set(round(float(z), 6) for z in levels))
    points = []
    seen = set()

    def add(x, y, z):
        pt = (float(x), float(y), float(z))
        key = tuple(round(v, 5) for v in pt)
        if key in seen:
            return
        if inside_container(container, pt, dims, margin=-0.006):
            seen.add(key)
            points.append(pt)

    legal_xlo = x_min + half[0] + 0.008
    legal_xhi = x_max - half[0] - 0.008
    legal_ylo = y_min + half[1] + 0.008
    legal_yhi = y_max - half[1] - 0.008
    if legal_xlo > legal_xhi or legal_ylo > legal_yhi:
        return []
    xmid = min(max(0.0, legal_xlo), legal_xhi)

    for z in levels:
        # Preserve back/front wall extrema at every feasible support level.
        for x, y in ((legal_xlo, legal_yhi), (legal_xhi, legal_yhi), (xmid, legal_yhi),
                     (legal_xlo, legal_ylo), (legal_xhi, legal_ylo), (xmid, legal_ylo)):
            add(x, y, z)

        z0, z1 = z-half[2], z+half[2]
        near = [b for b in packed_boxes if not (z1 < float(b[0][2])-0.04 or float(b[1][2]) < z0-0.04)]
        near.sort(key=lambda b: (-float(b[1][1]), float(b[0][0])))
        for lo, hi, _meta in near[:12]:
            x_left = float(lo[0]) - half[0] - 0.018
            x_right = float(hi[0]) + half[0] + 0.018
            y_front = float(lo[1]) - half[1] - 0.018
            bx = float((lo[0] + hi[0]) * 0.5)
            by = float((lo[1] + hi[1]) * 0.5)
            for x, y in ((x_left, legal_yhi), (x_right, legal_yhi),
                         (bx, y_front), (legal_xlo, y_front), (legal_xhi, y_front)):
                add(x, y, z)
            # If this level sits on the box, include 3x3 support samples.
            if abs((z-half[2]) - float(hi[2]) - 0.006) <= 0.025:
                xs = (float(lo[0]), bx, float(hi[0]))
                ys = (float(lo[1]), by, float(hi[1]))
                for yy in ys:
                    for xx in xs:
                        add(xx, yy, z)
            if len(points) >= max_candidates:
                return points[:max_candidates]
    points.sort(key=lambda p: (p[2], -p[1], abs(p[0])))
    return points[:max_candidates]


def residual_strip_score(support, center, dims, sliver_ratio=0.28):
    x0, x1, y0, y1 = (float(v) for v in support['rect'])
    cx, cy = float(center[0]), float(center[1])
    dx, dy = float(dims[0]), float(dims[1])
    edges = (cx-dx/2-x0, x1-(cx+dx/2), cy-dy/2-y0, y1-(cy+dy/2))
    threshold = max(0.025, min(dx, dy) * sliver_ratio)
    penalty = 0.0
    flush_bonus = 0.0
    for gap in edges:
        if abs(gap) <= 0.012:
            flush_bonus += 0.25
        elif 0.0 < gap < threshold:
            penalty += (threshold-gap) / threshold
    return float(flush_bonus - penalty)


def _effective_transport_height(container, center, dims):
    """Mirror the validator's vertical lift/clipping logic in local coordinates."""
    c = np.asarray(center, dtype=np.float64)
    half = np.asarray(dims, dtype=np.float64) * 0.5
    t = float(container.get('thickness', 0.04))
    h = float(container['height'])
    buffer = float(container.get('buffer', 0.01))
    effective = 0.08
    bottom = float(c[2] - half[2])
    for rz in (t, h/2 + t + buffer):
        if 0.0 <= bottom-rz <= 0.05:
            effective = 0.0
            break
    top = float(c[2] + half[2])
    if effective > 0.0:
        for cz in (h/2 + buffer, h + buffer - t):
            clearance = cz - top
            if 0.0 <= clearance < effective + 0.018:
                effective = max(0.0, clearance - 0.018 - 0.0005)
                break
    return min(h + buffer - t - half[2] - 0.01, float(c[2] + effective))


def _xz_to_pixel_bounds(container, depth_shape, x0, x1, z0, z1, pad_px=1):
    hpx, wpx = int(depth_shape[0]), int(depth_shape[1])
    length = float(container['length'])
    height = float(container['height'])
    target_aspect = wpx / max(hpx, 1)
    container_aspect = length / max(height, 1e-9)
    if container_aspect > target_aspect:
        phys_w = length
        phys_h = length / target_aspect
    else:
        phys_h = height
        phys_w = height * target_aspect
    center_z = float(container.get('center', (0.0, 0.0, height/2))[2])

    def u_of(x):
        return (float(x) + phys_w/2) / phys_w * wpx

    def v_of(z):
        z_rel = float(z) - center_z
        return (phys_h/2 - z_rel) / phys_h * hpx

    ua, ub = sorted((u_of(x0), u_of(x1)))
    va, vb = sorted((v_of(z0), v_of(z1)))
    u0 = max(0, int(math.floor(ua)) - pad_px)
    u1 = min(wpx, int(math.ceil(ub)) + pad_px + 1)
    v0 = max(0, int(math.floor(va)) - pad_px)
    v1 = min(hpx, int(math.ceil(vb)) + pad_px + 1)
    return u0, u1, v0, v1


def depth_reachable(container, depth_map, center, dims, safety_margin=0.015):
    """Conservative depth-image test of the validator's Y-then-X side-entry sweep."""
    if depth_map is None:
        return True, 0.0
    depth = np.asarray(depth_map, dtype=np.float64)
    if depth.ndim != 2 or depth.size == 0:
        return True, 0.0
    c = np.asarray(center, dtype=np.float64)
    dx, dy, dz = (float(v) for v in dims)
    t = float(container.get('thickness', 0.04))
    l = float(container['length'])
    w = float(container['width'])
    cut_x = float(container.get('cut_x', 0.0))
    start_margin = 0.01
    x_min = -l/2 + t + cut_x + dx/2 + start_margin
    x_max = l/2 - t - dx/2 - start_margin
    if x_min <= x_max:
        start_x = min(max(float(c[0]), x_min), x_max)
    else:
        start_x = float(c[0])
    path_z = _effective_transport_height(container, c, dims)
    x0 = min(start_x, float(c[0])) - dx/2 - safety_margin
    x1 = max(start_x, float(c[0])) + dx/2 + safety_margin
    z0 = path_z - dz/2 - safety_margin
    z1 = path_z + dz/2 + safety_margin
    u0, u1, v0, v1 = _xz_to_pixel_bounds(container, depth.shape, x0, x1, z0, z1, pad_px=1)
    if u1 <= u0 or v1 <= v0:
        return False, -1.0
    region = depth[v0:v1, u0:u1]
    if region.size == 0:
        return False, -1.0
    # A depth-map pixel is a ray sample, not an occupied pixel area.  Using the
    # absolute minimum makes a one-pixel rasterisation fringe (e.g. the edge of
    # a shelf just below the swept band) reject an otherwise clear corridor.
    # Known packed items/shelves are checked analytically by _known_path_clear;
    # the depth image is therefore used as a robust sensor for unmodelled tilt
    # and settling.  Reject if a material fraction of the swept rays is zero,
    # otherwise use a low quantile rather than the single minimum.
    flat = region.reshape(-1)
    zero_fraction = float(np.mean(flat <= 1e-8))
    if zero_fraction >= 0.10:
        return False, -1.0
    positive = flat[flat > 1e-8]
    if positive.size == 0:
        return False, -1.0
    sensed_depth = float(np.quantile(positive, 0.10))
    # available_depth is measured from the door plane into +Y.
    door_y = -w/2
    required = float(c[1] - door_y) + dy/2 + float(safety_margin)
    clearance = sensed_depth - required
    return bool(clearance >= 0.0), clearance


def _packed_boxes(container):
    out = []
    offset = _container_offset_x(container)
    for item in container.get('packed_items', []):
        if item.get('pos') is None or item.get('orn') is None:
            continue
        lo, hi = packed_item_aabb(item, offset)
        out.append((lo, hi, item))
    return out


def _shelf_collision_boxes(container):
    l = float(container['length'])
    w = float(container['width'])
    h = float(container['height'])
    t = float(container.get('thickness', 0.04))
    cut_x = float(container.get('cut_x', 0.0))
    buffer = float(container.get('buffer', 0.01))
    top = h/2 + t + buffer
    boxes = []
    if cut_x > 1e-9:
        boxes.append((
            np.asarray((-l/2+t, -w/2+t, top-t), dtype=np.float64),
            np.asarray((-l/2+t+cut_x, w/2-t, top), dtype=np.float64),
            {'kind': 'small_shelf'}
        ))
    if bool(container.get('shelf', False)):
        boxes.append((
            np.asarray((-l/2+t/2, t, top-t), dtype=np.float64),
            np.asarray((l/2-t/2, w/2-t, top), dtype=np.float64),
            {'kind': 'shelf'}
        ))
    return boxes


def _aabb_overlaps(lo_a, hi_a, lo_b, hi_b, penetration_tol=0.001):
    for axis in range(3):
        if float(hi_a[axis]) <= float(lo_b[axis]) + penetration_tol:
            return False
        if float(hi_b[axis]) <= float(lo_a[axis]) + penetration_tol:
            return False
    return True


def _target_clear(center, dims, boxes):
    c = np.asarray(center, dtype=np.float64)
    half = np.asarray(dims, dtype=np.float64) * 0.5
    lo, hi = c-half, c+half
    for blo, bhi, _meta in boxes:
        if _aabb_overlaps(lo, hi, blo, bhi):
            return False
    return True


def _known_path_clear(container, center, dims, boxes, safety_margin=0.015):
    """AABB approximation of the validator's Y-then-X insertion sweep.

    This is deliberately separate from the depth-image test: packed item AABBs
    and shelf geometry are known exactly enough to reject obvious swept-volume
    collisions, while depth_map handles tilt/settling not captured by AABBs.
    """
    c = np.asarray(center, dtype=np.float64)
    half = np.asarray(dims, dtype=np.float64) * 0.5
    l = float(container['length'])
    w = float(container['width'])
    t = float(container.get('thickness', 0.04))
    cut_x = float(container.get('cut_x', 0.0))
    x_min = -l/2 + t + cut_x + half[0] + 0.01
    x_max = l/2 - t - half[0] - 0.01
    start_x = min(max(float(c[0]), x_min), x_max) if x_min <= x_max else float(c[0])
    path_z = _effective_transport_height(container, c, dims)
    sm = float(safety_margin)

    # Segment 1: move in +Y from the door plane at clamped start_x.
    lo1 = np.asarray((
        start_x-half[0]-sm,
        min(-w/2, float(c[1]))-half[1]-sm,
        path_z-half[2]-sm,
    ), dtype=np.float64)
    hi1 = np.asarray((
        start_x+half[0]+sm,
        max(-w/2, float(c[1]))+half[1]+sm,
        path_z+half[2]+sm,
    ), dtype=np.float64)
    # Segment 2: translate in X at target Y and the same elevated Z.
    lo2 = np.asarray((
        min(start_x, float(c[0]))-half[0]-sm,
        float(c[1])-half[1]-sm,
        path_z-half[2]-sm,
    ), dtype=np.float64)
    hi2 = np.asarray((
        max(start_x, float(c[0]))+half[0]+sm,
        float(c[1])+half[1]+sm,
        path_z+half[2]+sm,
    ), dtype=np.float64)
    for blo, bhi, _meta in boxes:
        # Here touching the safety-expanded sweep is intentionally a collision.
        if _aabb_overlaps(lo1, hi1, blo, bhi, penetration_tol=0.0):
            return False
        if _aabb_overlaps(lo2, hi2, blo, bhi, penetration_tol=0.0):
            return False
    return True


def _unique_orientations(item):
    seen = set()
    values = []
    for orn in range(6):
        dims = orientation_dims(item, orn)
        key = tuple(round(float(v), 8) for v in dims)
        if key in seen:
            continue
        seen.add(key)
        values.append((orn, dims))
    # Broad, low orientations first for stability and search efficiency.
    values.sort(key=lambda od: (od[1][2], -(od[1][0]*od[1][1]), od[0]))
    return values


def _min_support_ratio(item):
    """Static-stability threshold for candidate support overlap.

    The COM must additionally be supported.  Heavy rigid luggage is allowed a
    modest overhang; soft/priority luggage gets a stricter footprint threshold.
    """
    if bool(item.get('is_soft', False)):
        return 0.80
    if bool(item.get('is_prioritized', False)):
        return 0.82
    return 0.74 if float(item.get('mass', 1.0)) >= 12.0 else 0.70


def _support_attributes_allowed(item, supporters):
    is_soft = bool(item.get('is_soft', False))
    is_priority = bool(item.get('is_prioritized', False))
    for s in supporters:
        if s['kind'] != 'item':
            continue
        meta = s.get('meta', {})
        if bool(meta.get('is_soft', False)) and not is_soft:
            return False
        if bool(meta.get('is_prioritized', False)) and not is_priority:
            return False
    return True


def _offline_rescue_support_allowed(item, supporters, packed_count, total_items):
    """Late Task-A rescue trade-off.

    Never crush a soft support with a hard item.  A priority support may carry a
    non-priority item only after roughly 45% of the stream has already been
    packed, where preserving fill/item count becomes more valuable than a small
    placement-score penalty.
    """
    is_soft = bool(item.get('is_soft', False))
    is_priority = bool(item.get('is_prioritized', False))
    late = int(packed_count) >= max(12, int(math.ceil(0.45 * max(int(total_items), 1))))
    for support in supporters:
        if support.get('kind') != 'item':
            continue
        meta = support.get('meta', {})
        if bool(meta.get('is_soft', False)) and not is_soft:
            return False
        if bool(meta.get('is_prioritized', False)) and not is_priority and not late:
            return False
    return True


def _container_used_volume(container):
    return sum(float(i['length'])*float(i['width'])*float(i['height']) for i in container.get('packed_items', []))


def _primary_support_for(center, dims, supporters):
    if not supporters:
        return None
    # Prefer real-item surface, then shelf, then floor; nearest support z wins.
    rank = {'item': 0, 'shelf': 1, 'small_shelf': 1, 'floor': 2}
    return min(supporters, key=lambda s: (rank.get(s['kind'], 3), -float(s['z'])))


def _candidate_score(item, container, center, dims, support_ratio, supporters,
                     reach_margin, pool_mean_volume, all_containers):
    dx, dy, dz = (float(v) for v in dims)
    vol = dx*dy*dz
    mass = float(item.get('mass', 1.0))
    h = max(float(container['height']), 1e-6)
    w = max(float(container['width']), 1e-6)
    cvol = max(float(container.get('volume', 1.0)), 1e-6)
    z_norm = float(center[2]) / h
    backness = (float(center[1]) + w/2) / w
    is_soft = bool(item.get('is_soft', False))
    is_priority = bool(item.get('is_prioritized', False))

    score = 0.0
    score += 10.0 * float(support_ratio)
    # Reachability is a feasibility/safety signal, not a packing objective.
    # Rewarding raw clearance biases actions toward the door (larger clearance).
    # Known-body sweep already enforces safety, so do not add positive clearance.
    score += 4.0 * min(vol / max(pool_mean_volume, 1e-9), 2.5)
    score += 1.8 * (dx*dy) / max(vol ** (2.0/3.0), 1e-9)
    score -= (2.5 + 0.32*mass) * z_norm

    primary = _primary_support_for(center, dims, supporters)
    if primary is not None:
        score += 2.4 * residual_strip_score(primary, center, dims)
        if primary['kind'] == 'floor':
            score += 0.9 + 0.12*mass

    # Structural luggage packs back/low first; fragile/retrieval-sensitive luggage front/up later.
    if is_soft or is_priority:
        # Fragile / retrieval-sensitive baggage is deliberately kept toward the
        # door and away from being a structural base.
        score += 3.0 * (1.0-backness)
        score += 0.7 * z_norm
    else:
        # Structural baggage builds a monotone back-to-front wall.  This term is
        # intentionally strong enough to dominate centre-placement aesthetics.
        score += 6.0 * backness

    priority_containers = [c for c in all_containers if bool(c.get('is_prioritized', False))]
    if is_priority and priority_containers:
        score += 32.0 if bool(container.get('is_prioritized', False)) else -45.0
    elif not is_priority and bool(container.get('is_prioritized', False)) and priority_containers:
        # Reserve dedicated capacity unless it would otherwise be unused.
        score -= 5.0

    used = _container_used_volume(container)
    score += 1.0 * max(0.0, 1.0-used/cvol)
    return float(score)


def _pool_selection_indices(pool, max_items=14):
    def key(pair):
        idx, item = pair
        soft = bool(item.get('is_soft', False))
        priority = bool(item.get('is_prioritized', False))
        structural_class = 0 if (not soft and not priority) else (1 if priority and not soft else 2)
        vol = float(item['length'])*float(item['width'])*float(item['height'])
        mass = float(item.get('mass', 1.0))
        return (structural_class, -vol, -mass, idx)
    ordered = sorted(enumerate(pool), key=key)
    if len(ordered) <= max_items:
        return [i for i, _ in ordered]
    chosen = ordered[:max_items]
    # Preserve at least one representative of each special class that exists.
    for pred in (
        lambda x: bool(x.get('is_prioritized', False)),
        lambda x: bool(x.get('is_soft', False)),
    ):
        special = next(((i, it) for i, it in ordered if pred(it)), None)
        if special is not None and special[0] not in {i for i, _ in chosen}:
            chosen[-1] = special
    return [i for i, _ in chosen]


def _enumerate_candidates(observation, max_checks=4800, per_surface_limit=220, use_depth=True):
    pool = list(observation.get('pool_list', []))
    containers = list(observation.get('container_list', []))
    depth_maps = observation.get('depth_map')
    if not pool or not containers:
        return []
    mean_vol = sum(float(i['length'])*float(i['width'])*float(i['height']) for i in pool) / len(pool)
    selected_indices = _pool_selection_indices(pool)
    results = []

    # A single hard-to-place item/orientation must not consume the entire 8 s
    # search budget.  Split checks across lookahead items, containers and unique
    # orientations.  Surface generation itself is also round-robin, giving this
    # three levels of fairness under bounded runtime.
    item_base = max(1, int(max_checks) // max(len(selected_indices), 1))
    item_extra = max(0, int(max_checks) - item_base*len(selected_indices))

    for item_rank, pool_idx in enumerate(selected_indices):
        item = pool[pool_idx]
        item_budget = item_base + (1 if item_rank < item_extra else 0)
        orientations = _unique_orientations(item)
        slots = max(1, len(containers) * len(orientations))
        slot_base = max(1, item_budget // slots)
        slot_extra = max(0, item_budget - slot_base*slots)
        slot_rank = 0

        for container_idx, container in enumerate(containers):
            supports = reconstruct_supports(container)
            packed = _packed_boxes(container)
            obstacles = packed + _shelf_collision_boxes(container)
            depth = None
            if use_depth and depth_maps is not None and len(depth_maps) > container_idx:
                depth = depth_maps[container_idx]

            for orn, dims in orientations:
                slot_budget = slot_base + (1 if slot_rank < slot_extra else 0)
                slot_rank += 1
                points = surface_candidate_centers(
                    container, dims, supports, packed,
                    max_candidates=min(per_surface_limit, max(slot_budget, 1)),
                )
                checked = 0
                for center in points:
                    if checked >= slot_budget:
                        break
                    checked += 1
                    if not _target_clear(center, dims, obstacles):
                        continue
                    if not _known_path_clear(container, center, dims, obstacles):
                        continue
                    ratio, center_ok, supporters = support_metrics(center, dims, supports)
                    if ratio < _min_support_ratio(item) or not center_ok:
                        continue
                    if not _support_attributes_allowed(item, supporters):
                        continue
                    reach_ok, reach_margin = depth_reachable(container, depth, center, dims) if use_depth else (True, 0.05)
                    # The official validator checks transport collisions only against
                    # already-packed items and shelves.  Those known bodies were
                    # conservatively checked above with _known_path_clear.  The 64x64
                    # depth map is too coarse to be a hard gate near the back wall or
                    # shelf edges, so a negative depth reading becomes a soft signal.
                    if not reach_ok:
                        reach_margin = min(float(reach_margin), -0.001)
                    score = _candidate_score(item, container, center, dims, ratio, supporters,
                                             reach_margin, mean_vol, containers)
                    results.append({
                        'item_idx': int(pool_idx),
                        'container_idx': int(container_idx),
                        'place_pos': np.asarray(center, dtype=np.float32),
                        'orientation': int(orn),
                        'score': float(score),
                        'support_ratio': float(ratio),
                        'reach_margin': float(reach_margin),
                    })
    results.sort(key=lambda r: (r['score'], -float(r['place_pos'][2]), float(r['place_pos'][1])), reverse=True)
    return results


def _quat_from_euler_xyz(roll, pitch, yaw):
    cr, sr = math.cos(roll/2), math.sin(roll/2)
    cp, sp = math.cos(pitch/2), math.sin(pitch/2)
    cy, sy = math.cos(yaw/2), math.sin(yaw/2)
    return (
        sr*cp*cy - cr*sp*sy,
        cr*sp*cy + sr*cp*sy,
        cr*cp*sy - sr*sp*cy,
        cr*cp*cy + sr*sp*sy,
    )


_ORIENTATION_EULERS = (
    (0.0, 0.0, 0.0),
    (math.pi/2, 0.0, 0.0),
    (0.0, math.pi/2, 0.0),
    (0.0, 0.0, math.pi/2),
    (0.0, math.pi/2, math.pi/2),
    (math.pi/2, 0.0, math.pi/2),
)


def _virtual_add(container, item, candidate):
    new_item = dict(item)
    p = candidate['place_pos']
    offset = _container_offset_x(container)
    new_item['pos'] = (float(p[0])+offset, float(p[1]), float(p[2]))
    new_item['orn'] = _quat_from_euler_xyz(*_ORIENTATION_EULERS[int(candidate['orientation'])])
    new_item['belongs_to'] = int(container.get('index', 0))
    container.setdefault('packed_items', []).append(new_item)


def _quick_future_bonus(observation, first_candidate):
    pool = list(observation.get('pool_list', []))
    if len(pool) <= 1:
        return 0.0
    containers = [dict(c, packed_items=[dict(i) for i in c.get('packed_items', [])]) for c in observation.get('container_list', [])]
    first_item = pool[int(first_candidate['item_idx'])]
    _virtual_add(containers[int(first_candidate['container_idx'])], first_item, first_candidate)
    remaining = [item for i, item in enumerate(pool) if i != int(first_candidate['item_idx'])]
    # Only inspect a few structurally important future items; this is the shallow beam's second ply.
    future_indices = _pool_selection_indices(remaining, max_items=min(3, len(remaining)))
    feasible = 0
    best = -1e9
    for ridx in future_indices:
        item = remaining[ridx]
        subobs = {
            'pool_list': [item],
            'container_list': containers,
            'depth_map': None,
            'lookahead_k': 1,
            'optimize': False,
        }
        cand = _enumerate_candidates(subobs, max_checks=420, per_surface_limit=70, use_depth=False)
        if cand:
            feasible += 1
            best = max(best, cand[0]['score'])
    return 0.8*feasible + (0.06*best if best > -1e8 else -1.5)


def _safe_recovery_action(observation):
    pool = list(observation.get('pool_list', []))
    containers = list(observation.get('container_list', []))
    depth_maps = observation.get('depth_map')
    if not pool or not containers:
        return {'item_idx': 0, 'container_idx': 0,
                'place_pos': np.asarray((0.0, 0.0, 0.5), dtype=np.float32), 'orientation': 0}
    item_order = sorted(range(len(pool)), key=lambda i: (
        float(pool[i]['length'])*float(pool[i]['width'])*float(pool[i]['height']),
        float(pool[i].get('mass', 1.0)), i))
    for pool_idx in item_order:
        item = pool[pool_idx]
        for container_idx, container in enumerate(containers):
            supports = reconstruct_supports(container)
            packed = _packed_boxes(container)
            obstacles = packed + _shelf_collision_boxes(container)
            depth = depth_maps[container_idx] if depth_maps is not None and len(depth_maps) > container_idx else None
            for orn, dims in _unique_orientations(item):
                pts = surface_candidate_centers(container, dims, supports, packed, max_candidates=120)
                pts += _extreme_candidate_centers(container, dims, packed, max_candidates=180)
                # De-duplicate while preserving rescue diversity.
                dedup = {}
                for pt in pts:
                    dedup.setdefault(tuple(round(float(v), 5) for v in pt), pt)
                pts = list(dedup.values())
                # Recovery prefers low/front points that are easier to insert.
                pts.sort(key=lambda p: (p[2], p[1], abs(p[0])))
                for center in pts:
                    if not _target_clear(center, dims, obstacles):
                        continue
                    if not _known_path_clear(container, center, dims, obstacles):
                        continue
                    ratio, center_ok, supporters = support_metrics(center, dims, supports)
                    if ratio < 0.72 or not center_ok:
                        continue
                    if not _support_attributes_allowed(item, supporters):
                        continue
                    # Depth is intentionally not a hard gate in recovery; known
                    # bodies have already passed the conservative swept-AABB test.
                    return {
                        'item_idx': int(pool_idx), 'container_idx': int(container_idx),
                        'place_pos': np.asarray(center, dtype=np.float32), 'orientation': int(orn),
                    }
    # Last-resort action with the smallest item, lowest orientation, near the door-side floor.
    pool_idx = item_order[0]
    item = pool[pool_idx]
    for container_idx, container in enumerate(containers):
        floor = next(s for s in reconstruct_supports(container) if s['kind'] == 'floor')
        for orn, dims in _unique_orientations(item):
            x0, x1, y0, y1 = floor['rect']
            center = (0.0, y0 + dims[1]/2 + 0.008, floor['z'] + dims[2]/2 + 0.008)
            if inside_container(container, center, dims, margin=-0.006):
                return {'item_idx': int(pool_idx), 'container_idx': int(container_idx),
                        'place_pos': np.asarray(center, dtype=np.float32), 'orientation': int(orn)}
    return {'item_idx': int(pool_idx), 'container_idx': 0,
            'place_pos': np.asarray((0.0, 0.0, 0.5), dtype=np.float32), 'orientation': 0}


def _offline_static_key(item):
    soft = bool(item.get('is_soft', False))
    priority = bool(item.get('is_prioritized', False))
    structural_class = 0 if (not soft and not priority) else (1 if priority and not soft else 2)
    vol = float(item['length'])*float(item['width'])*float(item['height'])
    mass = float(item.get('mass', 1.0))
    # Large/heavy rigid luggage creates the structural base; soft luggage is delayed.
    return (structural_class, -mass, -vol, int(item.get('index', 0)))


def _offline_structure_bias(item):
    soft = bool(item.get('is_soft', False))
    priority = bool(item.get('is_prioritized', False))
    if not soft and not priority:
        return 8.0 + 0.18*float(item.get('mass', 1.0))
    if priority and not soft:
        return 1.0
    if soft and priority:
        return -4.0
    return -3.0


def _select_frontier_candidate(candidates, pool, containers):
    """Stage rigid scaffold construction, then fragile/priority backfill."""
    if not candidates:
        return None
    rigid = [c for c in candidates
             if not bool(pool[c['item_idx']].get('is_soft', False))
             and not bool(pool[c['item_idx']].get('is_prioritized', False))]
    special = [c for c in candidates
               if bool(pool[c['item_idx']].get('is_soft', False))
               or bool(pool[c['item_idx']].get('is_prioritized', False))]
    if not rigid:
        return max(candidates, key=lambda c: c['score'])
    best_rigid = max(rigid, key=lambda c: c['score'])
    if not special:
        return best_rigid
    best_special = max(special, key=lambda c: c['score'])
    packed = [i for cont in containers for i in cont.get('packed_items', [])]
    soft_count = sum(bool(i.get('is_soft', False)) for i in packed)
    # One early soft bag may occupy an otherwise awkward low/front slot.  After
    # a substantial rigid scaffold exists, progressively backfill fragile cargo
    # when its geometric fit is materially better than the remaining rigid fit.
    early_backfill = (soft_count == 0
                      and best_special['score'] > best_rigid['score'] + 1.5
                      and float(best_special['place_pos'][2]) < 0.35)
    late_backfill = (len(packed) >= 20
                     and best_special['score'] > best_rigid['score'] + 2.0)
    return best_special if (early_backfill or late_backfill) else best_rigid


class Agent:
    def __init__(self, module_path: str):
        self.module_path = module_path
        self.containers = []
        self.lookahead_k = 1
        self.optimize_enabled = False
        self.offline_rank = {}
        self.offline_container_pref = {}
        self.offline_plan = {}
        self._offline_extreme_planner = None

    def get_init_states(self, init_states: dict):
        self.containers = list(init_states.get('container_list', []))
        self.lookahead_k = int(init_states.get('lookahead_k', 1))
        self.optimize_enabled = bool(init_states.get('optimize', False))
        self.offline_rank = {}
        self.offline_container_pref = {}
        self.offline_plan = {}
        self._offline_extreme_planner = None
        return True

    def optimize(self, item_list: list):
        """Build Task-A order and exact targets with the extreme-point planner.

        The offline phase has a 180 s budget and sees the complete stream.  A
        separate, battle-tested extreme-point planner is used here because it
        explores side-fill locations that a pure horizontal-support frontier can
        miss late in a dense packing.  Online policy still revalidates every
        planned target against the current observed scene before using it.
        """
        self.offline_rank = {}
        self.offline_container_pref = {}
        self.offline_plan = {}
        self._offline_extreme_planner = None
        if not item_list:
            return []
        if not self.containers:
            ordered = sorted(item_list, key=_offline_static_key)
            out = [int(i['index']) for i in ordered]
            self.offline_rank = {item_id: rank for rank, item_id in enumerate(out)}
            return out

        planner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'offline_extreme_planner.py')
        try:
            spec = importlib.util.spec_from_file_location('_surface_frontier_extreme_planner', planner_path)
            if spec is None or spec.loader is None:
                raise ImportError('cannot load offline extreme planner')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            planner = module.Agent(os.path.dirname(planner_path))
            planner.get_init_states({
                'optimize': True,
                'lookahead_k': max(1, self.lookahead_k),
                'container_list': copy.deepcopy(self.containers),
            })
            planned = list(planner.optimize(copy.deepcopy(item_list)))
            self._offline_extreme_planner = planner
            expected = {int(i['index']) for i in item_list}
            if len(planned) != len(item_list) or set(int(v) for v in planned) != expected:
                raise ValueError('offline planner did not return an exact permutation')
            planned = [int(v) for v in planned]
            self.offline_plan = {
                int(k): {
                    'container_idx': int(v['container_idx']),
                    'place_pos': np.asarray(v['place_pos'], dtype=np.float32).copy(),
                    'orientation': int(v['orientation']),
                }
                for k, v in getattr(planner, 'offline_plan', {}).items()
            }
        except Exception:
            # Never let an auxiliary offline planner break the submission.  A
            # deterministic structural order remains valid under the official
            # timeout/fallback contract.
            ordered = sorted(item_list, key=_offline_static_key)
            planned = [int(i['index']) for i in ordered]
            self.offline_plan = {}
            self._offline_extreme_planner = None

        self.offline_rank = {item_id: rank for rank, item_id in enumerate(planned)}
        for item_id, plan in self.offline_plan.items():
            self.offline_container_pref[item_id] = int(plan['container_idx'])

        priority_containers = [
            i for i, c in enumerate(self.containers) if bool(c.get('is_prioritized', False))
        ]
        if priority_containers:
            for item in item_list:
                item_id = int(item['index'])
                if item_id not in self.offline_container_pref and bool(item.get('is_prioritized', False)):
                    self.offline_container_pref[item_id] = int(priority_containers[0])
        return planned

    def policy(self, observation: dict):
        # Task A can carry an exact target from the offline extreme-point planner.
        # Reuse it only while the observed real scene still satisfies the new
        # reachability/support model; settling drift automatically falls back to
        # the online surface-frontier policy.
        if observation.get('optimize') and self.offline_plan:
            pool = list(observation.get('pool_list', []))
            containers = list(observation.get('container_list', []))
            planned = []
            for pool_idx, item in enumerate(pool):
                item_id = int(item.get('index', -1))
                plan = self.offline_plan.get(item_id)
                if plan is not None:
                    planned.append((self.offline_rank.get(item_id, 10**9), pool_idx, item, plan))
            planned.sort(key=lambda row: (row[0], row[1]))
            for _rank, pool_idx, item, plan in planned:
                ci = int(plan.get('container_idx', -1))
                orn = int(plan.get('orientation', -1))
                if not (0 <= ci < len(containers) and 0 <= orn < 6):
                    continue
                container = containers[ci]
                center = np.asarray(plan.get('place_pos'), dtype=np.float64)
                if center.shape != (3,):
                    continue
                dims = orientation_dims(item, orn)
                if not inside_container(container, center, dims, margin=-0.005):
                    continue
                packed = _packed_boxes(container)
                obstacles = packed + _shelf_collision_boxes(container)
                if not _target_clear(center, dims, obstacles):
                    continue
                if not _known_path_clear(container, center, dims, obstacles):
                    continue
                supports = reconstruct_supports(container)
                sr, center_ok, supporters = support_metrics(center, dims, supports, z_tol=0.035)
                if not center_ok or sr + 1e-9 < _min_support_ratio(item):
                    continue
                if not _support_attributes_allowed(item, supporters):
                    continue
                return {
                    'item_idx': int(pool_idx),
                    'container_idx': ci,
                    'place_pos': np.asarray(center, dtype=np.float32),
                    'orientation': orn,
                }

        # After the exact pre-plan prefix is exhausted, Task A can still benefit
        # from the extreme-point recovery policy.  It is treated only as a
        # proposal generator: the current scene is revalidated with the stricter
        # surface/reachability rules before its action can reach the simulator.
        if observation.get('optimize') and self._offline_extreme_planner is not None:
            try:
                proposed = self._offline_extreme_planner.policy(observation)
            except Exception:
                proposed = None
            if isinstance(proposed, dict):
                pool = list(observation.get('pool_list', []))
                containers = list(observation.get('container_list', []))
                pi = int(proposed.get('item_idx', -1))
                ci = int(proposed.get('container_idx', -1))
                orn = int(proposed.get('orientation', -1))
                if 0 <= pi < len(pool) and 0 <= ci < len(containers) and 0 <= orn < 6:
                    item = pool[pi]
                    container = containers[ci]
                    center = np.asarray(proposed.get('place_pos'), dtype=np.float64)
                    if center.shape == (3,):
                        dims = orientation_dims(item, orn)
                        packed = _packed_boxes(container)
                        obstacles = packed + _shelf_collision_boxes(container)
                        supports = reconstruct_supports(container)
                        sr, center_ok, supporters = support_metrics(center, dims, supports, z_tol=0.035)
                        if (inside_container(container, center, dims, margin=-0.005)
                                and _target_clear(center, dims, obstacles)
                                and _known_path_clear(container, center, dims, obstacles)
                                and center_ok
                                and sr + 1e-9 >= max(0.62, _min_support_ratio(item) - 0.08)
                                and _offline_rescue_support_allowed(
                                    item, supporters,
                                    packed_count=sum(len(c.get('packed_items', [])) for c in containers),
                                    total_items=max(len(self.offline_rank), 1),
                                )):
                            return {
                                'item_idx': pi,
                                'container_idx': ci,
                                'place_pos': np.asarray(center, dtype=np.float32),
                                'orientation': orn,
                            }

        # Broad but bounded single-ply surface-frontier search.  Empirically this
        # is both faster and more robust than re-enumerating the scene for several
        # second-ply beam branches under the official 8 s policy limit.
        candidates = _enumerate_candidates(
            observation, max_checks=18000, per_surface_limit=600, use_depth=True
        )
        if not candidates:
            return _safe_recovery_action(observation)

        # Apply offline order/container preference without forcing stale planned
        # coordinates: physical settling can move earlier luggage.
        if observation.get('optimize') and self.offline_rank:
            for c in candidates:
                item = observation['pool_list'][c['item_idx']]
                item_id = int(item.get('index', -1))
                rank = self.offline_rank.get(item_id, 10**6)
                c['score'] += max(0.0, 5.0 - 0.08*rank)
                pref = self.offline_container_pref.get(item_id)
                if pref is not None:
                    c['score'] += 2.5 if int(c['container_idx']) == int(pref) else -0.8
            candidates.sort(key=lambda r: r['score'], reverse=True)

        best = _select_frontier_candidate(
            candidates, observation['pool_list'], observation.get('container_list', [])
        )
        if best is None:
            return _safe_recovery_action(observation)
        return {
            'item_idx': int(best['item_idx']),
            'container_idx': int(best['container_idx']),
            'place_pos': np.asarray(best['place_pos'], dtype=np.float32),
            'orientation': int(best['orientation']),
        }

