"""Test official-legal raised release targets above supported landing roots.

This reads frozen observation-only candidate/native/preview code. It imports no
official simulator source and does not run an episode.
"""
import argparse
from collections import deque
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np

parser=argparse.ArgumentParser()
parser.add_argument('--output',required=True)
parser.add_argument('--timing-contended',action='store_true')
parser.add_argument('--max-previews',type=int,default=8)
parser.add_argument('--max-native-checks',type=int,default=2500)
parser.add_argument('--only',choices=['historical23','native20','progressive22'])
parser.add_argument('--require-no-volume-loss',action='store_true')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
source=root/'native_candidate_packing/variants/progressive_recovery'
spec=importlib.util.spec_from_file_location('controlled_drop_source',source/'__init__.py',submodule_search_locations=[str(source)])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from controlled_drop_source.agent import Agent
from controlled_drop_source import historical as h
from controlled_drop_source.candidates import mixed_points,SharedPoints
from controlled_drop_source.native import NativeValidator
from controlled_drop_source.preview import SettlingPreview

record=dict(probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            source_path=str(source),source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('*.py')},
            timing_contended=args.timing_contended,require_no_volume_loss=args.require_no_volume_loss,
            drops=[.06,.12,.18,.24],snapshots=[])
paths=[('historical23',root/'fair_candidate_packing/results/baseline-b-task001-seed42.snapshot.json'),
       ('native20',root/'native_candidate_packing/results/native-b-task001-seed42.snapshot.json'),
       ('progressive22',root/'native_candidate_packing/results/progressive-b-task001-seed42.snapshot.json')]
if args.only: paths=[entry for entry in paths if entry[0]==args.only]
for name,path in paths:
    started=time.perf_counter()
    obs=json.loads(path.read_text())
    pool,containers=obs['pool_list'],obs['container_list']
    geometry=[(h._packed_boxes_for_container(c),h._shelf_boxes(c)) for c in containers]
    helper=Agent(str(source))
    helper._current_geometry=geometry
    pending=deque()
    point_cache={}
    acceptance_cache={}
    for pi,item in sorted(enumerate(pool),key=lambda pair:(-h._item_urgency(pair[1]),pair[0])):
        for orn,dims in h._unique_orientations(item):
            for ci,c in enumerate(containers):
                key=(ci,tuple(dims))
                if key not in point_cache:
                    point_cache[key]=SharedPoints(mixed_points(c,dims,geometry[ci][0],max_points=300))
                pending.append((pi,ci,orn,dims,iter(point_cache[key])))
    roots=[]
    seen=set()
    checks=0
    while pending and checks<6500:
        pi,ci,orn,dims,points=pending.popleft()
        try: center=next(points)
        except StopIteration: continue
        pending.append((pi,ci,orn,dims,points))
        checks+=1
        cargo,c=pool[pi],containers[ci]
        acceptance_key=(ci,tuple(dims),tuple(center),float(cargo.get('mass',1.))>=12.,bool(cargo.get('is_soft',False)))
        if acceptance_key not in acceptance_cache:
            acceptance_cache[acceptance_key]=helper._prefilter(cargo,c,dims,center,*geometry[ci])
        accepted,ratio,support_z=acceptance_cache[acceptance_key]
        if not accepted: continue
        physical=(ci,tuple(dims),float(cargo.get('mass',1.)),bool(cargo.get('is_soft',False)),tuple(round(float(v),5) for v in center))
        if physical in seen: continue
        seen.add(physical)
        score=h._score_candidate(cargo,c,dims,center,ratio,support_z,c.get('packed_items',[]),containers)
        landing=dict(item_idx=pi,container_idx=ci,orientation=orn,place_pos=np.asarray(center,dtype=np.float32))
        supports=helper._support_items(landing,obs)
        roots.append((score,landing,ratio,supports))
    roots.sort(key=lambda row:row[0],reverse=True)
    result=dict(name=name,snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                generated_checks=checks,unique_supported_roots=len(roots),native_checks=0,native_rejections={},
                previews=[],outcome='no_verified_recovery')
    validators={ci:NativeValidator(c) for ci,c in enumerate(containers)}
    landing_results={}
    for _,landing,_,_ in roots:
        key=(landing['item_idx'],landing['container_idx'],landing['orientation'],tuple(landing['place_pos']))
        landing_results[key]=validators[landing['container_idx']].check(pool[landing['item_idx']],landing)
    candidates=[]
    for drop in (.06,.12,.18,.24):
        for score,landing,ratio,supports in roots:
            if result['native_checks']>=args.max_native_checks: break
            key=(landing['item_idx'],landing['container_idx'],landing['orientation'],tuple(landing['place_pos']))
            landing_native=landing_results[key]
            if landing_native['transport']:
                continue  # Count only newly restored ingress from a raised target.
            action=dict(landing,place_pos=landing['place_pos'].copy())
            action['place_pos'][2]+=np.float32(drop)
            native=validators[action['container_idx']].check(pool[action['item_idx']],action)
            result['native_checks']+=1
            if all(native[key] for key in ('included','target_clear','transport')):
                candidates.append((drop,score,landing,action,ratio,supports,native,landing_native))
            else:
                for key in ('included','target_clear','transport'):
                    if not native[key]: result['native_rejections'][key]=result['native_rejections'].get(key,0)+1
    result['native_valid_raised_roots']=len(candidates)
    # Try different support/drop combinations before another shift on one tower.
    groups={}
    for candidate in candidates:
        group=(candidate[0],candidate[5])
        groups.setdefault(group,deque()).append(candidate)
    trials=deque()
    while groups:
        for group in list(groups):
            trials.append(groups[group].popleft())
            if not groups[group]: del groups[group]
    with SettlingPreview() as preview:
        while trials and len(result['previews'])<args.max_previews:
            drop,score,landing,action,ratio,supports,native,landing_native=trials.popleft()
            predicted=preview.evaluate(containers[action['container_idx']],pool[action['item_idx']],action)
            trace=dict(drop=drop,landing_center=landing['place_pos'].tolist(),support_ratio=ratio,
                       support_items=[list(s) for s in sorted(supports)],
                       action={key:value.tolist() if hasattr(value,'tolist') else value for key,value in action.items()},
                       native=native,unraised_native=landing_native,preview=predicted)
            result['previews'].append(trace)
            if (predicted['safe'] and predicted['steps']==300 and
                    (not args.require_no_volume_loss or predicted['lost_volume']==0.)):
                result.update(outcome='verified_raised_recovery',recovery=trace)
                break
    for validator in validators.values(): validator.close()
    result['seconds']=time.perf_counter()-started
    record['snapshots'].append(result)
    print(json.dumps(dict(name=name,outcome=result['outcome'],roots=len(roots),native_valid=len(candidates),
                          native_checks=result['native_checks'],preview_trials=len(result['previews']),seconds=result['seconds'])),flush=True)
output=Path(args.output)
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(record,indent=2))
