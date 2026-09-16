"""Boundary regression: finite floor and partially open front are distinct."""
import unittest
import json
import numpy as np
import pybullet as p
from probe import ROOT,load,fixtures

preview=load('finite_mesh_test',ROOT/'source')
mesh=__import__('finite_mesh_test.mesh',fromlist=['container_meshes'])

class FiniteGeometryTests(unittest.TestCase):
    def setUp(self):
        _,obs,_,_=next(fixtures())
        self.container=obs['container_list'][0]

    def test_inner_ring_matches_observed_wall_planes(self):
        vertices,_=mesh.container_meshes(self.container)[0]
        rotation=np.asarray(p.getMatrixFromQuaternion(p.getQuaternionFromEuler([np.pi/2,0,0]))).reshape(3,3)
        points=np.asarray(vertices[10:15])@rotation.T+np.asarray(self.container['center'])
        normals=np.asarray(self.container['n_vecs'])[:5]
        bases=np.asarray(self.container['points'])[:5]
        offsets=(points[:,None,:]-bases[None,:,:])*normals[None,:,:]
        distances=offsets.sum(axis=2)
        self.assertLess(float(distances.max()),1e-7)
        for row in distances:
            self.assertEqual(int(np.sum(np.abs(row)<1e-7)),2)

    def test_front_aperture_cut_closure_and_finite_floor(self):
        with preview.SettlingPreview() as scene:
            mesh.build_container(scene.client,self.container)
            def hit(start,end): return scene.client.rayTest(start,end)[0][0]>=0
            self.assertFalse(hit([.3,-1.,.4],[.3,-.5,.4]))
            self.assertTrue(hit([-.9,-1.,1.],[ -.9,-.5,1.]))
            self.assertFalse(hit([.3,-1.,.2],[.3,-1.,-.1]))
            self.assertTrue(hit([.3,0.,.2],[.3,0.,-.1]))

    def test_measured_initial_velocity_rejects_saved_drop(self):
        evidence=json.loads((ROOT/'velocity-replay.json').read_text())
        velocities={row['index']:(row['linear'],row['angular']) for row in evidence['measured_velocities']}
        _,obs,action,_=next(fixtures())
        with preview.SettlingPreview(velocity_overrides=velocities) as scene:
            result=scene.evaluate(obs['container_list'][0],obs['pool_list'][action['item_idx']],action)
        self.assertEqual(result['steps'],300)
        self.assertFalse(result['safe'])
        self.assertGreater(result['displacement'],.3)
        self.assertAlmostEqual(result['displacement'],.34213673961599433,places=5)

if __name__=='__main__': unittest.main()
