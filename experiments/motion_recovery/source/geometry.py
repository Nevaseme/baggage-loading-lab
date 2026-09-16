"""Small observation geometry helpers shared with settling preview."""
from types import SimpleNamespace
import numpy as np
import pybullet as p
from .native import ORIENTATIONS


def _orientation_quaternion(orientation):
    return p.getQuaternionFromEuler(ORIENTATIONS[orientation])


def _points_world(container):
    return np.asarray(container['n_vecs'],dtype=np.float64), np.asarray(container['points'],dtype=np.float64)


def _shelf_obbs(container):
    length,width,height = (float(container[k]) for k in ('length','width','height'))
    t,cut = float(container.get('thickness',.04)),float(container.get('cut_x',0.))
    center = container.get('center',[0.,0.,height/2])
    offset = float(center[0])
    buffer = float(container.get('buffer',float(center[2])-height/2))
    z = height/2+t/2+buffer
    shelves = [(SimpleNamespace(center=np.asarray([offset-length/2+cut/2+t,0.,z]),
                                 half=np.asarray([cut/2,width/2-t,t/2])), 'small_shelf')]
    if bool(container.get('shelf',container.get('require_shelf',False))):
        shelves.append((SimpleNamespace(center=np.asarray([offset,width/4,z]),
                                        half=np.asarray([length/2-t/2,width/4-t,t/2])), 'main_shelf'))
    return shelves
