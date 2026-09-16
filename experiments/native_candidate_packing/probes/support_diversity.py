"""Matched preview recovery with XY-basin versus actual-support deferral."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import pybullet as p

parser=argparse.ArgumentParser()
parser.add_argument('--output',required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
snapshot=root/'results/basin-preview-b-task001-seed42.snapshot.json'
obs=json.loads(snapshot.read_text())
record=dict(snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),trials=[])
support=next(item for item in obs['container_list'][0]['packed_items'] if item['index']==13)
rotation=np.asarray(p.getMatrixFromQuaternion(support['orn'])).reshape(3,3)
record['support_13']=dict(position=support['pos'],orientation=support['orn'],
                           tilt_degrees=math.degrees(math.acos(min(1.,float(np.max(np.abs(rotation[2])))))))
for label in ('basin_coverage','support_diverse_preview'):
    source=root/'variants'/label
    package_name=f'support_probe_{label}'
    spec=importlib.util.spec_from_file_location(package_name,source/'__init__.py',submodule_search_locations=[str(source)])
    package=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=package
    spec.loader.exec_module(package)
    module=__import__(package_name+'.agent',fromlist=['Agent'])
    agent=module.Agent(str(source))
    agent.use_settling_preview=True
    started=time.perf_counter()
    trial=dict(variant=label,source_hashes={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in source.glob('*.py')})
    try:
        action=agent.policy(obs)
        trial.update(outcome='returned',action={key:value.tolist() if hasattr(value,'tolist') else value for key,value in action.items()})
        native=agent._native[action['container_idx']].check(obs['pool_list'][action['item_idx']],action)
        trial['fresh_native']=native
    except Exception as error:
        trial.update(outcome=type(error).__name__,error=str(error))
    trial.update(seconds=time.perf_counter()-started,diagnostics=agent.last_diagnostics)
    record['trials'].append(trial)
    for validator in agent._native.values(): validator.close()
    if agent._preview is not None: agent._preview.close()
output=Path(args.output)
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(record,indent=2))
print(json.dumps(record))
