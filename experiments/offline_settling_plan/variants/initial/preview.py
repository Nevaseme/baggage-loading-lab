"""Private observation-only settling check; no simulator internals are imported.

Packed body velocities are unavailable, so the reconstruction starts at rest.
Planes reconstruct the container's convex interior and omit its open front.
"""
import math
import time

import numpy as np
import pybullet as p
from pybullet_utils.bullet_client import BulletClient

from .geometry import _orientation_quaternion, _points_world, _shelf_obbs


class SettlingPreview:
    def __init__(self):
        self.client = BulletClient(connection_mode=p.DIRECT)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.client is not None:
            self.client.disconnect()
            self.client = None

    def _spawn(self, item, pos, orn):
        c = self.client
        shape = c.createCollisionShape(p.GEOM_BOX, halfExtents=[float(item[k])*.5 for k in ('length','width','height')])
        body = c.createMultiBody(baseMass=float(item.get('mass', 1.)),
                                 baseCollisionShapeIndex=shape, basePosition=pos, baseOrientation=orn)
        defaults = dict(lateralFriction=.8, rollingFriction=.01, spinningFriction=.01,
                        restitution=0., angularDamping=.8)
        dynamics = {key: float(item.get(key, value)) for key, value in defaults.items()}
        if item.get('is_soft', False):
            dynamics.update({key: float(item.get(key, value)) for key, value in
                             dict(contactStiffness=5000., contactDamping=500., linearDamping=.8).items()})
        c.changeDynamics(body, -1, **dynamics)
        return body

    @staticmethod
    def _inside(item, pos, orn, normals, points, margin):
        half = np.asarray([float(item[key])*.5 for key in ('length','width','height')])
        rotation = np.asarray(p.getMatrixFromQuaternion(orn)).reshape(3,3)
        radius = np.abs(normals @ rotation) @ half
        dots = np.sum(normals * (np.asarray(pos)-points), axis=1) + radius
        return bool(np.all(dots <= margin))

    def evaluate(self, container, item, action, steps=300, inclusion_margin=-.005,
                 deadline=None, capture_final_state=False):
        """Run one private settling trial.

        The offline planner can request the settled pose of every existing
        body.  The default omits that extra payload for the online path.
        """
        started = time.perf_counter()
        c = self.client
        c.resetSimulation()
        c.setPhysicsEngineParameter(deterministicOverlappingPairs=1)
        c.setGravity(0., 0., -9.8)
        normals, points = _points_world(container)
        for normal, point in zip(normals, points):
            if normal[1] < -.9:
                continue  # The official container has an open front.
            shape = c.createCollisionShape(p.GEOM_PLANE, planeNormal=(-normal).tolist())
            body = c.createMultiBody(baseMass=0., baseCollisionShapeIndex=shape, basePosition=point.tolist())
            c.changeDynamics(body, -1, lateralFriction=.8, rollingFriction=.01, spinningFriction=.01)
        for shelf, _ in _shelf_obbs(container):
            shape = c.createCollisionShape(p.GEOM_BOX, halfExtents=shelf.half.tolist())
            c.createMultiBody(baseMass=0., baseCollisionShapeIndex=shape, basePosition=shelf.center.tolist())
        previous = []
        for packed in container.get('packed_items', []):
            body = self._spawn(packed, packed['pos'], packed['orn'])
            was_inside = self._inside(packed, packed['pos'], packed['orn'], normals, points, inclusion_margin)
            previous.append((body, packed, was_inside))
        target = np.asarray(action['place_pos'], dtype=np.float64).copy()
        target[0] += float(container.get('center', [0])[0])
        orn = _orientation_quaternion(int(action['orientation']))
        body = self._spawn(item, target.tolist(), orn)
        completed = 0
        for step in range(steps):
            if step % 25 == 0 and deadline is not None and time.perf_counter() >= deadline:
                break
            c.stepSimulation()
            completed += 1
        pos, final_orn = c.getBasePositionAndOrientation(body)
        displacement = float(np.linalg.norm(np.asarray(pos)-target))
        dot = min(1., abs(sum(a*b for a, b in zip(orn, final_orn))))
        angle = math.degrees(2.*math.acos(dot))
        newly_outside = []
        displaced = []
        lost_volume = 0.
        final_packed_items = []
        for old_body, packed, was_inside in previous:
            old_pos, old_orn = c.getBasePositionAndOrientation(old_body)
            was_displaced = float(np.linalg.norm(np.asarray(old_pos)-np.asarray(packed['pos'])))
            displaced.append(was_displaced)
            if capture_final_state:
                updated = dict(packed)
                updated['pos'] = list(old_pos)
                updated['orn'] = list(old_orn)
                final_packed_items.append(updated)
            if was_inside and not self._inside(packed, old_pos, old_orn, normals, points, inclusion_margin):
                newly_outside.append(int(packed['index']))
                lost_volume += float(packed['length'])*float(packed['width'])*float(packed['height'])
        result = dict(safe=completed == steps and displacement <= .3 and angle <= 45., displacement=displacement,
                      angle_degrees=angle, final_position=list(pos), final_orientation=list(final_orn),
                      seconds=time.perf_counter()-started, steps=completed, deadline_exceeded=completed < steps,
                      previously_inside=sum(inside for _, _, inside in previous),
                      newly_outside=newly_outside, lost_volume=lost_volume,
                      max_previous_displacement=max(displaced, default=0.), inclusion_margin=inclusion_margin)
        if capture_final_state:
            result['final_packed_items'] = final_packed_items
        return result
