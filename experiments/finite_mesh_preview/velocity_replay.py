"""Offline diagnostic only: replay saved actions, then isolate missing velocity.

The submission preview never imports the simulator. This diagnostic deliberately
uses the official environment to measure hidden state after a fixed saved prefix;
it invokes no Agent and performs no new policy search.
"""
from contextlib import redirect_stdout
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import time
import numpy as np
from probe import ROOT,NATIVE,load
from src.ground_handling.env import GroundHandlingEnv


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    result_path=ROOT.parent/'controlled_drop_recovery/results/drop-b-task001-seed42.json'
    snapshot_path=NATIVE/'results/progressive-b-task001-seed42.snapshot.json'
    saved=json.loads(result_path.read_text())
    snapshot=json.loads(snapshot_path.read_text())
    action=copy.deepcopy(saved['records'][22]['action'])
    action['place_pos']=np.asarray(action['place_pos'],dtype=np.float32)
    record=dict(timing_contended=True,diagnostic_only=True,prefix_length=22,
        result_sha256=digest(result_path),snapshot_sha256=digest(snapshot_path),
        script_sha256=digest(Path(__file__)),source_hashes={p.name:digest(p) for p in (ROOT/'source').glob('*.py')},
        simulator_hashes={p.name:digest(p) for p in (ROOT.parent.parent/'simulator/src/ground_handling').glob('*.py')},
        action={key:value.tolist() if hasattr(value,'tolist') else value for key,value in action.items()})
    started=time.perf_counter()
    environment=None
    with (ROOT/'velocity-replay.log').open('w') as log,redirect_stdout(log):
        try:
            random.seed(saved['seed'])
            np.random.seed(saved['seed'])
            environment=GroundHandlingEnv(copy.deepcopy(saved['config']),verbose=False)
            environment.reset_settings()
            environment.reset_item_stream()
            observation,_=environment.reset(seed=saved['seed'])
            for row in saved['records'][:22]:
                replay_action=copy.deepcopy(row['action'])
                replay_action['place_pos']=np.asarray(replay_action['place_pos'],dtype=np.float32)
                observation,_,terminated,truncated,info=environment.step(replay_action)
                assert all(info['status'].values()),(row['step'],info)
                assert not terminated and not truncated
            record['replay_seconds']=time.perf_counter()-started
            record['observed_cargo_matches_snapshot']=json.dumps(observation['container_list'],sort_keys=True)==json.dumps(snapshot['container_list'],sort_keys=True)
            assert record['observed_cargo_matches_snapshot'],'Replay does not match source state'
            velocities={}
            velocity_rows=[]
            packed=[]
            for container in environment.container_manager.containers:
                for item in container.packed_items:
                    linear,angular=environment.client.getBaseVelocity(item.pybullet_id)
                    packed.append(item)
                    velocities[item.index]=(linear,angular)
                    velocity_rows.append(dict(index=item.index,linear=list(linear),angular=list(angular),
                        linear_speed=float(np.linalg.norm(linear)),angular_speed=float(np.linalg.norm(angular))))
            record['measured_velocities']=sorted(velocity_rows,key=lambda row:row['linear_speed'],reverse=True)
            item=environment.stream_manager.get_item(action['item_idx'])
            container=environment.container_manager.get_container(action['container_idx'])
            target=container.local_to_global(action['place_pos'])
            assert environment.validator.check_inclusion(container,item,target,action['orientation'])
            assert environment.validator.check_transport_path(container,item,target,action['orientation'])
            client=environment.client
            state=client.saveState()
            quaternion=client.getQuaternionFromEuler([0,0,0])
            record['official_world_trials']=[]
            for zero_velocity in (False,True):
                client.restoreState(stateId=state)
                if zero_velocity:
                    for old_item in packed: client.resetBaseVelocity(old_item.pybullet_id,[0,0,0],[0,0,0])
                item.set_pose(client,target,quaternion)
                for _ in range(300): client.stepSimulation()
                pos,orn=item.get_pose(client)
                displacement=float(np.linalg.norm(np.asarray(pos)-target))
                angle=math.degrees(2*math.acos(min(1.,abs(sum(a*b for a,b in zip(quaternion,orn))))))
                record['official_world_trials'].append(dict(zero_packed_velocities=zero_velocity,steps=300,
                    displacement=displacement,angle_degrees=angle,safe=displacement<=.3 and angle<=45.,final_position=list(pos)))
            client.removeState(state)
        finally:
            if environment is not None: environment.close()
    module=load('velocity_finite',ROOT/'source')
    record['finite_trials']=[]
    for use_measured in (False,True):
        with module.SettlingPreview(velocity_overrides=velocities if use_measured else None) as preview:
            outcome=preview.evaluate(snapshot['container_list'][action['container_idx']],snapshot['pool_list'][action['item_idx']],action)
        record['finite_trials'].append(dict(use_measured_velocities=use_measured,**outcome))
    record['seconds']=time.perf_counter()-started
    (ROOT/'velocity-replay.json').write_text(json.dumps(record,indent=2))
    print(json.dumps({key:value for key,value in record.items() if key not in ('simulator_hashes','source_hashes','measured_velocities','finite_trials')}))
    print(json.dumps({'fastest_initial_items':record['measured_velocities'][:5],
        'finite_trials':[{key:row[key] for key in ('use_measured_velocities','safe','displacement','angle_degrees','seconds')} for row in record['finite_trials']]}))


if __name__=='__main__': main()
