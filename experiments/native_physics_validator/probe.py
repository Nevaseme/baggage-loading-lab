"""Compare native query parity and timings on saved actions and fixtures."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np

from native import NativeValidator

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
parser.add_argument('--timing-contended', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parent
fair = root.parent / 'fair_candidate_packing'
spec = importlib.util.spec_from_file_location('native_parity_reference', fair/'source/__init__.py', submodule_search_locations=[str(fair/'source')])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from native_parity_reference.authorizer import authorize_current, proposal_from_action

cases = []
for name in ('baseline-a-task000-seed42', 'baseline-b-task001-seed42',
             'baseline-c-task001-seed42', 'baseline-b-task001-shuffle17', 'aligned-b-task001-seed42'):
    result = json.loads((fair/'results'/f'{name}.json').read_text())
    snapshot_path = fair/'results'/f'{name}.snapshot.json'
    obs = json.loads(snapshot_path.read_text())
    cases.append((name, obs, result['records'][-1]['action'], hashlib.sha256(snapshot_path.read_bytes()).hexdigest()))
snapshot_path = fair/'results/fair-b-task001-seed42.snapshot.json'
obs = json.loads(snapshot_path.read_text())
recovery = json.loads((fair/'probes/candidate-generation-freeze.json').read_text())['trials'][1]['action']
cases.append(('fair_generation_recovery', obs, recovery, hashlib.sha256(snapshot_path.read_bytes()).hexdigest()))

def fixture(offset, gap=None):
    item = dict(index=0,length=.2,width=.2,height=.2,mass=1.,is_soft=False,is_prioritized=False)
    container = dict(index=0,length=2.,width=1.45,height=1.61,thickness=.04,buffer=0.,cut_x=.44,cut_y=.4,
                     center=[offset,0.,.805],shelf=False,require_shelf=False,packed_items=[],
                     n_vecs=[[-1,0,0],[1,0,0],[0,-1,0],[0,1,0],[0,0,-1],[0,0,1]],
                     points=[[offset-.96,0,0],[offset+.96,0,0],[offset,-.685,0],
                             [offset,.685,0],[offset,0,.04],[offset,0,1.57]])
    if gap is not None:
        container['packed_items'] = [dict(item,index=1,pos=[offset+.2+gap,0.,.15],orn=[0.,0.,0.,1.])]
    obs = dict(optimize=False,lookahead_k=1,pool_list=[item],container_list=[container])
    action = dict(item_idx=0,container_idx=0,orientation=0,place_pos=[0.,0.,.15])
    return obs, action

for name, offset, gap in (('offset_3m',3.,None),('contact_clear',0.,.015001),
                          ('contact_boundary',0.,.015),('contact_reject',0.,.014999)):
    obs, action = fixture(offset,gap)
    cases.append((name,obs,action,hashlib.sha256(json.dumps(obs,sort_keys=True).encode()).hexdigest()))

obs, action = fixture(0.)
obs['pool_list'][0]['length'] = 1.6
cases.append(('inverted_door_interval',obs,action,hashlib.sha256(json.dumps(obs,sort_keys=True).encode()).hexdigest()))
obs, action = fixture(3.)
obs['container_list'][0]['buffer'] = .06
obs['container_list'][0]['center'][2] += .06
action['place_pos'] = [.3, 0., .62]
cases.append(('buffered_midpoint_clip',obs,action,hashlib.sha256(json.dumps(obs,sort_keys=True).encode()).hexdigest()))

records = []
for name, obs, action, snapshot_hash in cases:
    action = dict(action,place_pos=np.asarray(action['place_pos'],dtype=np.float32))
    proposal = proposal_from_action(action,obs,route='native_probe',source_key=name)
    started = time.perf_counter()
    reference = authorize_current(proposal,obs)
    reference_seconds = time.perf_counter()-started
    with NativeValidator(obs['container_list'][action['container_idx']]) as validator:
        native = validator.check(obs['pool_list'][action['item_idx']],action)
        build_seconds = validator.build_seconds
        repeat = validator.check(obs['pool_list'][action['item_idx']],action)
    expected = {key: bool(reference.hard_evidence[field]) for key,field in
                (('transport','transport'),('included','plane_inclusion'),('target_clear','target_clear'))}
    parity = all(native[key] == value for key,value in expected.items())
    boundary_difference = (name == 'contact_boundary' and native['transport'] and not expected['transport']
                           and all(native[key] == expected[key] for key in ('included','target_clear')))
    records.append(dict(name=name,snapshot_sha256=snapshot_hash,action={key:value.tolist() if hasattr(value,'tolist') else value for key,value in action.items()},
                        native=native,native_repeat_seconds=repeat['seconds'],build_seconds=build_seconds,
                        reference=expected,reference_seconds=reference_seconds,parity=parity,
                        documented_boundary_difference=boundary_difference))
record = dict(source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.py')},
              authorizer_sha256=hashlib.sha256((fair/'source/authorizer.py').read_bytes()).hexdigest(),
              timing_contended=args.timing_contended,cases=records,
              all_parity=all(r['parity'] for r in records))
record['all_nonboundary_parity'] = all(r['parity'] or r['documented_boundary_difference'] for r in records)
output = Path(args.output)
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(record,indent=2))
print(json.dumps(dict(all_parity=record['all_parity'],cases=[dict(name=r['name'],parity=r['parity'],transport=r['native']['transport'],
                                                               native_seconds=r['native']['seconds'],reference_seconds=r['reference_seconds']) for r in records])))
raise SystemExit(0 if record['all_nonboundary_parity'] else 1)
