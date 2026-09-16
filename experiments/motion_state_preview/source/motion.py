"""Carry predicted motion between selected actions, using public poses only."""
import copy
import math
import numpy as np
import pybullet as p
from .preview import SettlingPreview


def _rotation_residual(actual,predicted):
    inverse=[-predicted[0],-predicted[1],-predicted[2],predicted[3]]
    _,delta=p.multiplyTransforms([0,0,0],actual,[0,0,0],inverse)
    delta=np.asarray(delta,dtype=float)
    if delta[3]<0: delta=-delta
    length=float(np.linalg.norm(delta[:3]))
    if length<1e-10: return np.zeros(3)
    return delta[:3]/length*(2*math.atan2(length,float(delta[3])))


class MotionStatePreview:
    """evaluate is speculative; accept commits only the action actually selected.

    No measured velocities, simulator client, or hidden environment state is read.
    The optional correction adds pose prediction residual / elapsed simulation time
    to carried velocity. A zero gain isolates pure predicted-velocity carry.
    """
    def __init__(self,residual_gain=0.,via_obj=False):
        self.residual_gain=float(residual_gain)
        self._preview=SettlingPreview(via_obj=via_obj)
        self._frame=None
        self.last_estimates={}

    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def close(self): self._preview.close()

    def _estimate(self,container):
        estimates={}
        frame=self._frame
        if frame is None or frame['container_index']!=int(container['index']): return estimates
        observed={int(item['index']):item for item in container.get('packed_items',[])}
        if set(observed)!=set(frame['states']): return estimates
        for index,item in observed.items():
            predicted=frame['states'][index]
            linear=np.asarray(predicted['linear'])+self.residual_gain*(np.asarray(item['pos'])-predicted['pos'])/1.25
            angular=np.asarray(predicted['angular'])+self.residual_gain*_rotation_residual(item['orn'],predicted['orn'])/1.25
            estimates[index]=(linear.tolist(),angular.tolist())
        return estimates

    def evaluate(self,container,item,action,steps=300,inclusion_margin=-.005,deadline=None):
        self.last_estimates=self._estimate(container)
        self._preview.velocity_overrides=self.last_estimates
        result=self._preview.evaluate(container,item,action,steps=steps,inclusion_margin=inclusion_margin,deadline=deadline)
        result['inferred_velocity_count']=len(self.last_estimates)
        result['motion_residual_gain']=self.residual_gain
        if result['steps']==300 and not result['deadline_exceeded']:
            result['_motion_frame']=dict(container_index=int(container['index']),states=result.pop('predicted_state'))
        else:
            result.pop('predicted_state',None)
        return result

    def accept(self,result):
        """Commit a complete preview after selecting that action; rejected trials never commit."""
        if result.get('steps')!=300 or result.get('deadline_exceeded') or '_motion_frame' not in result:
            raise ValueError('Only a complete 300-step selected-action preview can be committed')
        self._frame=copy.deepcopy(result['_motion_frame'])

    def reset(self):
        self._frame=None
        self.last_estimates={}
