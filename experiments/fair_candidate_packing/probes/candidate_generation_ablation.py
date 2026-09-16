"""Matched candidate-family on/off test on a fixed failed observation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = root / 'source'
snapshot = root / 'results/fair-b-task001-seed42.snapshot.json'
spec = importlib.util.spec_from_file_location('packing_candidate_probe', source / '__init__.py', submodule_search_locations=[str(source)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from packing_candidate_probe.agent import Agent
from packing_candidate_probe.authorizer import authorize_current, proposal_from_action
obs = json.loads(snapshot.read_text())
record = dict(source_hashes={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.glob('*.py')},
              snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(), trials=[])
for enabled in (False, True):
    agent = Agent(str(source))
    agent.use_support_candidates = enabled
    trial = dict(use_support_candidates=enabled)
    started = time.perf_counter()
    try:
        action = agent.policy(obs)
        trial.update(outcome='authorized', action={k: v.tolist() if hasattr(v, 'tolist') else v for k,v in action.items()})
        checked = authorize_current(proposal_from_action(action, obs, route='probe', source_key='ablation'), obs)
        trial.update(support_ratio=checked.settling_evidence['support_ratio'], transport_clearance=checked.hard_evidence['transport_min_clearance'])
    except Exception as error:
        trial.update(outcome=type(error).__name__, error=str(error))
    trial.update(seconds=time.perf_counter()-started, diagnostics=agent.last_diagnostics)
    record['trials'].append(trial)
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(record, indent=2))
print(json.dumps(record['trials']))
