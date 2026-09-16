import unittest
from native import NativeValidator


def fixture(offset=0.):
    container = dict(index=0,length=2.,width=1.45,height=1.61,thickness=.04,buffer=0.,cut_x=.44,
                     center=[offset,0.,.805],shelf=False,packed_items=[],
                     n_vecs=[[-1,0,0],[1,0,0],[0,-1,0],[0,1,0],[0,0,-1],[0,0,1]],
                     points=[[offset-.96,0,0],[offset+.96,0,0],[offset,-.685,0],
                             [offset,.685,0],[offset,0,.04],[offset,0,1.57]])
    item = dict(index=0,length=.2,width=.2,height=.2,mass=1.)
    action = dict(item_idx=0,container_idx=0,orientation=0,place_pos=[0.,0.,.15])
    return container,item,action


class NativeValidationTests(unittest.TestCase):
    def test_clear_action_translates_local_position_to_offset_container(self):
        c,it,a = fixture(3.)
        with NativeValidator(c) as validator:
            result = validator.check(it,a)
        self.assertTrue(result['included'])
        self.assertTrue(result['transport'])

    def test_packed_box_blocks_y_ingress(self):
        c,it,a = fixture()
        c['packed_items'] = [dict(it,index=1,pos=[0.,-.3,.15],orn=[0.,0.,0.,1.])]
        with NativeValidator(c) as validator:
            result = validator.check(it,a)
        self.assertFalse(result['transport'])
        self.assertEqual(result['failure_segment'],'y')

    def test_inverted_door_interval_keeps_official_clamp(self):
        c,it,a = fixture()
        it['length'] = 1.6
        with NativeValidator(c) as validator:
            result = validator.check(it,a)
        self.assertAlmostEqual(result['start_x'],.15)

    def test_deadline_never_accepts_unchecked_route(self):
        c,it,a = fixture()
        with NativeValidator(c) as validator:
            result = validator.check(it,a,deadline=0.)
        self.assertFalse(result['transport'])
        self.assertTrue(result['deadline_exceeded'])


if __name__ == '__main__':
    unittest.main()
