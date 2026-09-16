"""Explicit rejected action when search exhausts; the public API has no stop call.

This preserves official partial-episode evaluation instead of raising an agent
exception. It is an early termination, never a successful placement. Coordinates
respect the supplied action-space range [-100,100]; observed planes prove that
the item will be rejected before spawning or advancing the physical world.
"""
import numpy as np


def terminal_rejection(observation):
    container=observation['container_list'][0]
    item=observation['pool_list'][0]
    half=np.asarray([float(item[k])*.5 for k in ('length','width','height')])
    normals=np.asarray(container['n_vecs'],dtype=float)
    points=np.asarray(container['points'],dtype=float)
    for local in ((0.,0.,-99.),(0.,-99.,0.),(0.,99.,0.),(99.,0.,0.),(-99.,0.,0.),(0.,0.,99.)):
        pos=np.asarray(local,dtype=np.float32)
        world=pos.astype(float)
        world[0]+=float(container.get('center',[0.,0.,0.])[0])
        dots=np.sum(normals*(world-points),axis=1)+np.abs(normals)@half
        maximum=float(np.max(dots))
        if maximum>1.:
            return (dict(item_idx=0,container_idx=0,orientation=0,place_pos=pos),
                    dict(included=False,plane_max_dot=maximum,reason='bounded_search_exhausted'))
    raise ValueError('No rejected terminal action exists within the supplied action-space range')
