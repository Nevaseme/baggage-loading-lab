"""Fixed saved-action replay; measured velocity is evaluation truth only."""
from contextlib import redirect_stdout
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys
import time
import numpy as np
from src.ground_handling.env import GroundHandlingEnv

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('motion_probe_source',ROOT/'source/__init__.py',submodule_search_locations=[str(ROOT/'source')])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from motion_probe_source.motion import MotionStatePreview

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    saved_path=ROOT.parent/'controlled_drop_recovery/results/drop-b-task001-seed42.json'
    saved=json.loads(saved_path.read_text())
    record=dict(timing_contended=True,diagnostic_only=True,residual_gain=0.,result_sha256=digest(saved_path),
        source_hashes={p.name:digest(p) for p in (ROOT/'source').glob('*.py')},script_sha256=digest(Path(__file__)),trials=[])
    started=time.perf_counter()
    environment=None
    preview=MotionStatePreview()
    with (ROOT/'sequential-carry.log').open('w') as log,redirect_stdout(log):
        try:
            random.seed(saved['seed'])
            np.random.seed(saved['seed'])
            environment=GroundHandlingEnv(copy.deepcopy(saved['config']),verbose=False)
            environment.reset_settings()
            environment.reset_item_stream()
            observation,_=environment.reset(seed=saved['seed'])
            for step,row in enumerate(saved['records'][:23]):
                action=copy.deepcopy(row['action'])
                action['place_pos']=np.asarray(action['place_pos'],dtype=np.float32)
                container=observation['container_list'][action['container_idx']]
                cargo=observation['pool_list'][action['item_idx']]
                result=preview.evaluate(container,cargo,action)
                truth=[]
                for packed in environment.container_manager.containers[action['container_idx']].packed_items:
                    linear,angular=environment.client.getBaseVelocity(packed.pybullet_id)
                    estimated=preview.last_estimates.get(packed.index,([0,0,0],[0,0,0]))
                    truth.append(dict(index=packed.index,measured_linear=list(linear),measured_angular=list(angular),
                        inferred_linear=estimated[0],inferred_angular=estimated[1],
                        linear_error=float(np.linalg.norm(np.asarray(linear)-estimated[0])),
                        angular_error=float(np.linalg.norm(np.asarray(angular)-estimated[1]))))
                trial=dict(step=step,action=row['action'],actual_safe=row['status']['is_placed_safe'],
                    state_sha256=hashlib.sha256(json.dumps({'container':container,'pool':observation['pool_list']},sort_keys=True).encode()).hexdigest(),
                    preview=result,velocity_truth=truth)
                record['trials'].append(trial)
                print(f'preview step={step} safe={result["safe"]} displacement={result["displacement"]:.6f}',flush=True)
                if step==22: break
                # Only the public observation and complete selected-action preview enter accept.
                preview.accept(result)
                observation,_,terminated,truncated,info=environment.step(action)
                assert all(info['status'].values()),(step,info)
                assert not terminated and not truncated
        finally:
            preview.close()
            if environment is not None: environment.close()
    record['seconds']=time.perf_counter()-started
    record['false_reject_steps']=[trial['step'] for trial in record['trials'] if trial['actual_safe'] and not trial['preview']['safe']]
    record['false_safe_steps']=[trial['step'] for trial in record['trials'] if not trial['actual_safe'] and trial['preview']['safe']]
    (ROOT/'sequential-carry.json').write_text(json.dumps(record,indent=2))
    print(json.dumps({key:record[key] for key in ('seconds','false_reject_steps','false_safe_steps')}))
    print(json.dumps([{key:trial['preview'][key] for key in ('displacement','angle_degrees','seconds','inferred_velocity_count')}
        for trial in record['trials'][-3:]]))

if __name__=='__main__': main()
