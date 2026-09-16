"""Compare finite and plane preview against saved full-episode outcomes."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
NATIVE=ROOT.parent/'native_candidate_packing'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path/'__init__.py',submodule_search_locations=[str(path)])
    package=importlib.util.module_from_spec(spec)
    sys.modules[name]=package
    spec.loader.exec_module(package)
    return __import__(name+'.preview',fromlist=['SettlingPreview'])

def fixtures():
    drop=json.loads((ROOT.parent/'controlled_drop_recovery/policy-freeze.json').read_text())['trials'][1]['action']
    rows=[('drop_bad','progressive-b-task001-seed42',drop,False),
          ('native20_safe','native-b-task001-seed42',dict(item_idx=0,container_idx=0,orientation=3,
            place_pos=[.7388619780540466,-.33933404088020325,1.1566648483276367]),True),
          ('support17_safe','basin-preview-b-task001-seed42',dict(item_idx=0,container_idx=0,orientation=2,
            place_pos=[-.18069152534008026,-.5099999904632568,.963105320930481]),True),
          ('tower_bad','aligned-b-task001-seed42',dict(item_idx=0,container_idx=0,orientation=0,
            place_pos=[.5826834440231323,-.2478378713130951,1.033853530883789]),False)]
    for name,stem,action,actual_safe in rows:
        snapshot=NATIVE/'results'/f'{stem}.snapshot.json'
        if not snapshot.exists(): snapshot=ROOT.parent/'fair_candidate_packing/results'/f'{stem}.snapshot.json'
        observation=json.loads(snapshot.read_text())
        yield name,observation,action,dict(snapshot=str(snapshot.relative_to(ROOT.parent.parent)),
            snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),actual_safe=actual_safe)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--timing-contended',action='store_true')
    args=parser.parse_args()
    sources=[('planes',ROOT.parent/'controlled_drop_recovery/source'),('finite',ROOT/'source')]
    modules={name:load('calibration_'+name,path) for name,path in sources}
    record=dict(timing_contended=args.timing_contended,source_hashes={name:{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.glob('*.py')} for name,path in sources},trials=[])
    for name,observation,action,evidence in fixtures():
        row=dict(fixture=name,action=action,**evidence,predictions={})
        for variant,module in modules.items():
            with module.SettlingPreview() as preview:
                row['predictions'][variant]=preview.evaluate(observation['container_list'][action['container_idx']],
                    observation['pool_list'][action['item_idx']],action)
        record['trials'].append(row)
        print(json.dumps(row),flush=True)
    Path(args.output).write_text(json.dumps(record,indent=2))

if __name__=='__main__': main()
