"""Native observation-only geometry validation using official transport semantics.

No simulator modules are imported. The scene contains static observed cargo and
shelves because transport queries do not advance physics. Settling is separate.
"""
import math
import time

import numpy as np
import pybullet as p
from pybullet_utils.bullet_client import BulletClient

ORIENTATIONS = ((0.,0.,0.), (math.pi/2,0.,0.), (0.,math.pi/2,0.),
                (0.,0.,math.pi/2), (0.,math.pi/2,math.pi/2), (math.pi/2,0.,math.pi/2))
PERMUTATIONS = ((0,1,2),(0,2,1),(2,1,0),(1,0,2),(1,2,0),(2,0,1))


class NativeValidator:
    def __init__(self, container, *, safety_margin=.015, start_z=.08,
                 ceiling_margin=.018, inclusion_margin=-.005, step_len=.01):
        started = time.perf_counter()
        self.container = container
        self.safety_margin = safety_margin
        self.start_z = start_z
        self.ceiling_margin = ceiling_margin
        self.inclusion_margin = inclusion_margin
        self.step_len = step_len
        self.client = BulletClient(connection_mode=p.DIRECT)
        self.obstacles = []
        self.offset_x = float(container.get('center', [0.,0.,0.])[0])
        self.buffer = float(container.get('buffer', float(container.get('center', [0.,0.,float(container['height'])/2])[2])-float(container['height'])/2))
        for item in container.get('packed_items', []):
            half = [float(item[key])/2 for key in ('length','width','height')]
            position = list(item['pos'])
            if item.get('position_is_local', False):
                position[0] += self.offset_x
            self.obstacles.append(self._box(half, position, item['orn']))
        length, width, height = (float(container[k]) for k in ('length','width','height'))
        thickness, cut = float(container.get('thickness', .04)), float(container.get('cut_x', 0.))
        shelf_z = height/2 + thickness/2 + self.buffer
        self.obstacles.append(self._box([cut/2,width/2-thickness,thickness/2],
                                       [self.offset_x-length/2+cut/2+thickness,0.,shelf_z]))
        if bool(container.get('shelf', container.get('require_shelf', False))):
            self.obstacles.append(self._box([length/2-thickness/2,width/4-thickness,thickness/2],
                                           [self.offset_x,width/4,shelf_z]))
        self.build_seconds = time.perf_counter()-started

    def _box(self, half, pos, orn=(0.,0.,0.,1.)):
        shape = self.client.createCollisionShape(p.GEOM_BOX, halfExtents=half)
        return self.client.createMultiBody(baseMass=0., baseCollisionShapeIndex=shape,
                                           basePosition=pos, baseOrientation=orn)

    def close(self):
        if self.client is not None:
            self.client.disconnect()
            self.client = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def check(self, item, action, *, deadline=None):
        started = time.perf_counter()
        c = self.container
        length, width, height = (float(c[key]) for key in ('length','width','height'))
        thickness, cut = float(c.get('thickness', .04)), float(c.get('cut_x', 0.))
        orientation = int(action['orientation'])
        original = np.asarray([float(item[key]) for key in ('length','width','height')])
        half = original[list(PERMUTATIONS[orientation])]/2
        # Match official float32 action values, then translate the local target.
        local = np.asarray(action['place_pos'], dtype=np.float32).astype(np.float64)
        world = local.copy()
        world[0] += self.offset_x
        normals, points = np.asarray(c['n_vecs']), np.asarray(c['points'])
        dots = np.sum(normals*(world-points), axis=1) + np.abs(normals) @ half
        included = bool(np.all(dots <= self.inclusion_margin))
        lift = self.start_z
        for surface in (thickness, height/2+thickness+self.buffer):
            if 0. <= world[2]-half[2]-surface <= .05:
                lift = 0.
                break
        if lift > 0.:
            for ceiling in (height/2+self.buffer, height+self.buffer-thickness):
                clearance = ceiling-world[2]-half[2]
                if 0. <= clearance < lift+self.ceiling_margin:
                    lift = max(0., clearance-self.ceiling_margin-.0005)
                    break
        start_x = min(max(local[0], -length/2+thickness+cut+half[0]+.01),
                      length/2-thickness-half[0]-.01)
        path_z = min(height+self.buffer-thickness-half[2]-.01, world[2]+lift)
        start = np.asarray([start_x+self.offset_x,-width/2,path_z])
        target0 = np.asarray([start[0],world[1],start[2]])
        target1 = np.asarray([world[0],world[1],start[2]])
        quaternion = p.getQuaternionFromEuler(ORIENTATIONS[orientation])
        body = self._box((original/2).tolist(), world.tolist(), quaternion)
        record = dict(included=included, plane_max_dot=float(np.max(dots)),
                      target_clear=True, transport=True, effective_lift=float(lift),
                      path_z=float(path_z), start_x=float(start_x), samples=0,
                      failure_segment=None, failure_distance=None, deadline_exceeded=False)
        try:
            for obstacle in self.obstacles:
                if any(point[8] < -1e-9 for point in self.client.getClosestPoints(body, obstacle, 0.)):
                    record['target_clear'] = False
            for segment, first, last in (('y',start,target0), ('x',target0,target1)):
                distance = abs(float(last[1]-first[1])) if segment == 'y' else abs(float(last[0]-first[0]))
                steps = max(math.ceil(distance/self.step_len), 1)
                for sample in range(steps+1):
                    if deadline is not None and time.perf_counter() >= deadline:
                        record.update(transport=False, deadline_exceeded=True, failure_segment=segment)
                        return record
                    pos = first+(last-first)*(sample/steps)
                    self.client.resetBasePositionAndOrientation(body, pos.tolist(), quaternion)
                    self.client.performCollisionDetection()
                    record['samples'] += 1
                    for obstacle in self.obstacles:
                        contacts = self.client.getClosestPoints(body, obstacle, self.safety_margin)
                        if contacts:
                            record.update(transport=False, failure_segment=segment,
                                          failure_distance=min(float(point[8]) for point in contacts))
                            return record
            return record
        finally:
            self.client.removeBody(body)
            record['seconds'] = time.perf_counter()-started
