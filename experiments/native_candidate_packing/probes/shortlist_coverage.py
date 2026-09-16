"""Test whether score trimming discards exact-valid candidate basins."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('--output',required=True)
parser.add_argument('--timing-contended',action='store_true')
parser.add_argument('--source',default='source')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
source=root/args.source
spec=importlib.util.spec_from_file_location('shortlist_coverage_source',source/'__init__.py',submodule_search_locations=[str(source)])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from shortlist_coverage_source.agent import Agent
from shortlist_coverage_source.preview import SettlingPreview

record=dict(source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('*.py')},
            timing_contended=args.timing_contended,trials=[])
for name,backfill in (('native-b-task001-seed42',0.),('native-backfill8-b-task001-seed42',8.)):
    path=root/'results'/f'{name}.snapshot.json'
    obs=json.loads(path.read_text())
    for label,limit in (('current',96),('wide',4096)):
        agent=Agent(str(source))
        agent.shortlist_limit=limit
        agent.max_authorizations=512 if label=='wide' else 96
        agent.backfill_weight=backfill
        started=time.perf_counter()
        trial=dict(snapshot=name,snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                   variant=label,shortlist_limit=limit,max_authorizations=agent.max_authorizations,
                   backfill_weight=backfill,max_candidate_checks=agent.max_candidate_checks)
        try:
            action=agent.policy(obs)
            trial.update(outcome='returned',action={k:v.tolist() if hasattr(v,'tolist') else v for k,v in action.items()})
        except Exception as error:
            trial.update(outcome=type(error).__name__,error=str(error))
            action=None
        trial.update(seconds=time.perf_counter()-started,diagnostics=agent.last_diagnostics)
        if action is not None:
            with SettlingPreview() as preview:
                trial['preview']=preview.evaluate(obs['container_list'][action['container_idx']],obs['pool_list'][action['item_idx']],action)
        record['trials'].append(trial)
        for validator in agent._native.values(): validator.close()
output=Path(args.output)
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(record,indent=2))
print(json.dumps([dict(snapshot=t['snapshot'],variant=t['variant'],outcome=t['outcome'],seconds=t['seconds'],
                       checks=t['diagnostics']['candidate_checks'],native_checks=t['diagnostics']['authorizations'],
                       preview_safe=t.get('preview',{}).get('safe')) for t in record['trials']]))
