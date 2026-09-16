"""Reproduce observation-only preview calibration; run with simulator Python."""
import argparse
import copy
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
spec = importlib.util.spec_from_file_location('packing_preview_probe', source / '__init__.py', submodule_search_locations=[str(source)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from packing_preview_probe.agent import Agent
from packing_preview_probe.preview import SettlingPreview

snapshot = root / 'results/aligned-b-task001-seed42.snapshot.json'
obs = json.loads(snapshot.read_text())
actual = json.loads((root / 'results/aligned-b-task001-seed42.json').read_text())
failed_action = actual['records'][-1]['action']
record = dict(source_hashes={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.glob('*.py')},
              snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
              actual_failure=actual['records'][-1], trials=[])
with SettlingPreview() as preview:
    for steps in (150, 300):
        result = preview.evaluate(obs['container_list'][failed_action['container_idx']],
                                  obs['pool_list'][failed_action['item_idx']], failed_action, steps=steps)
        record['trials'].append(dict(action=failed_action, **result))
    stable_container = copy.deepcopy(obs['container_list'][failed_action['container_idx']])
    stable_container['packed_items'] = []
    stable_item = obs['pool_list'][failed_action['item_idx']]
    floor_action = dict(item_idx=failed_action['item_idx'], container_idx=failed_action['container_idx'],
                        orientation=0, place_pos=[.3, .25, stable_container['thickness']+stable_item['height']*.5+.008])
    record['stable_control'] = dict(action=floor_action,
                                    **preview.evaluate(stable_container, stable_item, floor_action))
agent = Agent(str(source))
agent.use_settling_preview = True
started = time.perf_counter()
try:
    action = agent.policy(obs)
    record['recovery'] = dict(outcome='authorized_and_preview_safe', action={k: v.tolist() if hasattr(v, 'tolist') else v for k,v in action.items()})
except Exception as error:
    record['recovery'] = dict(outcome=type(error).__name__, error=str(error))
record['recovery']['seconds'] = time.perf_counter()-started
record['recovery']['diagnostics'] = agent.last_diagnostics
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(record, indent=2))
print(json.dumps(record['recovery']))
if agent._preview is not None:
    agent._preview.close()
