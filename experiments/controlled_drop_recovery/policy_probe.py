"""Save source-hashed matched controller evidence on progressive22."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from test_policy import root,native_root,control,treatment,close

parser=argparse.ArgumentParser()
parser.add_argument('--output',required=True)
args=parser.parse_args()
snapshot=native_root/'results/progressive-b-task001-seed42.snapshot.json'
obs=json.loads(snapshot.read_text())
record=dict(snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),trials=[])
for name,module,directory in (('progressive',control,native_root/'variants/progressive_recovery'),
                              ('controlled_drop',treatment,root/'source')):
    agent=module.Agent(str(directory))
    trial=dict(variant=name,source_hashes={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.glob('*.py')})
    started=time.perf_counter()
    try:
        action=agent.policy(obs)
        trial.update(outcome='returned',action={key:value.tolist() if hasattr(value,'tolist') else value for key,value in action.items()})
    except Exception as error:
        trial.update(outcome=type(error).__name__,error=str(error))
    trial.update(seconds=time.perf_counter()-started,diagnostics=agent.last_diagnostics)
    record['trials'].append(trial)
    close(agent)
Path(args.output).write_text(json.dumps(record,indent=2))
print(json.dumps(record))
