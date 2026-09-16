"""Can full basin coverage recover the original historical B stop?"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('--output',required=True)
parser.add_argument('--search-seconds',type=float,default=1.5)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
source=root/'variants/support_diverse_preview'
snapshot=root.parent/'fair_candidate_packing/results/baseline-b-task001-seed42.snapshot.json'
obs=json.loads(snapshot.read_text())
spec=importlib.util.spec_from_file_location('historical_recovery_probe',source/'__init__.py',submodule_search_locations=[str(source)])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from historical_recovery_probe.agent import Agent
agent=Agent(str(source))
agent.preview_search_seconds=args.search_seconds
record=dict(source_hashes={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in source.glob('*.py')},
            snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),preview_search_seconds=args.search_seconds)
started=time.perf_counter()
try:
    action=agent.policy(obs)
    record.update(outcome='returned',action={key:value.tolist() if hasattr(value,'tolist') else value for key,value in action.items()})
except Exception as error:
    record.update(outcome=type(error).__name__,error=str(error))
record.update(seconds=time.perf_counter()-started,diagnostics=agent.last_diagnostics)
Path(args.output).write_text(json.dumps(record,indent=2))
print(json.dumps(record))
for validator in agent._native.values(): validator.close()
if agent._preview is not None: agent._preview.close()
