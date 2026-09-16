"""Footprint-aligned and dense candidates, balanced across support surfaces."""
from collections import deque
import itertools

import numpy as np

from . import historical as h


def _surfaces(container, dims, packed):
    half = np.asarray(dims) * .5
    floor_center = h._floor_z(container) + .008 + half[2]
    bounds = h._center_bounds(container, dims, floor_center)
    if bounds is not None:
        xlo, xhi, ylo, yhi = bounds
        yield floor_center, (xlo-half[0], xhi+half[0], ylo-half[1], yhi+half[1])
    # Fixed shelves are available independently of older, crowded box surfaces.
    shelves = h._shelf_boxes(container)
    for lo, hi, meta in shelves + sorted(packed, key=lambda b: (-b[1][1], b[1][2])):
        gap = .018 if meta.get('kind') else .006
        yield float(hi[2]) + gap + half[2], (float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1]))


def _support_points(container, dims, packed, z, rect, dense):
    bounds = h._center_bounds(container, dims, z)
    if bounds is None:
        return
    xlo, xhi, ylo, yhi = bounds
    hx, hy = dims[0] * .5, dims[1] * .5
    lx, ux, ly, uy = rect
    clamp = lambda value, lower, upper: min(max(value, lower), upper)
    if dense:
        # Sample centers over the support, including bounded overhangs. The
        # historical acceptance predicate still enforces area/center support.
        xs = np.linspace(max(xlo, lx), min(xhi, ux), 9)
        ys = np.linspace(min(yhi, uy), max(ylo, ly), 9)
    else:
        xs = [clamp(v, xlo, xhi) for v in (lx+hx, ux-hx, (lx+ux)*.5)]
        ys = [clamp(v, ylo, yhi) for v in (uy-hy, ly+hy, (ly+uy)*.5)]
    for y, x in itertools.product(ys, xs):
        if xlo <= x <= xhi and ylo <= y <= yhi:
            yield float(x), float(y), float(z)
    if not dense:
        # Align with neighbors as well as the selected support boundary.
        for lo, hi, _ in packed:
            if hi[2] < z-dims[2]*.5-.02 or lo[2] > z+dims[2]*.5+.02:
                continue
            for y in ys:
                for x in (lo[0]-hx-.018, hi[0]+hx+.018):
                    if xlo <= x <= xhi:
                        yield float(x), float(y), float(z)
            y = lo[1]-hy-.018
            if ylo <= y <= yhi:
                for x in xs:
                    yield float(x), float(y), float(z)


def support_points(container, dims, packed, dense=False):
    streams = deque(iter(_support_points(container, dims, packed, z, rect, dense))
                    for z, rect in _surfaces(container, dims, packed))
    seen = set()
    while streams:
        stream = streams.popleft()
        try:
            point = next(stream)
        except StopIteration:
            continue
        streams.append(stream)
        key = tuple(round(v, 5) for v in point)
        if key not in seen:
            seen.add(key)
            yield point


def mixed_points(container, dims, packed, max_points=300):
    """Each family gets a turn; crowded low tops cannot hide all shelf roots."""
    streams = deque([iter(support_points(container, dims, packed)),
                     iter(h._candidate_points(container, dims, packed, max_points=max_points)),
                     iter(support_points(container, dims, packed, dense=True))])
    seen = set()
    while streams:
        stream = streams.popleft()
        try:
            point = next(stream)
        except StopIteration:
            continue
        streams.append(stream)
        key = tuple(round(v, 5) for v in point)
        if key not in seen:
            seen.add(key)
            yield point
