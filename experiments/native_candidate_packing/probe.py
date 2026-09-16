"""Matched saved-state probe for native-only versus settling-preview recovery."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('--output',required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parent
source=root/'source'
spec=importlib.util.spec_from_file_location('native_candidate_probe',source/'__init__.py',submodule_search_locations=[str(source)])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from native_candidate_probe.agent import Agent

record=dict(source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('*.py')},trials=[])
for name in ('baseline-b-task001-seed42','aligned-b-task001-seed42'):
    path=root.parent/'fair_candidate_packing/results'/f'{name}.snapshot.json'
    obs=json.loads(path.read_text())
    for preview in (False,True):
        agent=Agent(str(source))
        agent.use_settling_preview=preview
        started=time.perf_counter()
        trial=dict(snapshot=name,snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),use_settling_preview=preview)
        try:
            action=agent.policy(obs)
            trial.update(outcome='returned',action={k:v.tolist() if hasattr(v,'tolist') else v for k,v in action.items()})
        except Exception as error:
            trial.update(outcome=type(error).__name__,error=str(error))
        trial.update(seconds=time.perf_counter()-started,diagnostics=agent.last_diagnostics)
        record['trials'].append(trial)
        for validator in agent._native.values():
            validator.close()
        if agent._preview is not None:
            agent._preview.close()
output=Path(args.output)
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(record,indent=2))
print(json.dumps(record['trials']))
