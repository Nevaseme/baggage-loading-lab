"""Isolate in-memory versus OBJ mesh loader, with identical generated geometry."""
import hashlib
import json
from pathlib import Path
from probe import ROOT,load,fixtures

module=load('finite_obj_probe',ROOT/'source')
name,obs,action,evidence=next(fixtures())
record=dict(fixture=name,action=action,**evidence,source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
    for p in (ROOT/'source').glob('*.py')},trials=[])
for via_obj in (False,True):
    with module.SettlingPreview(via_obj=via_obj) as preview:
        result=preview.evaluate(obs['container_list'][action['container_idx']],obs['pool_list'][action['item_idx']],action)
    row=dict(via_obj=via_obj,**result)
    record['trials'].append(row)
    print(json.dumps(row),flush=True)
(ROOT/'obj-loader-calibration.json').write_text(json.dumps(record,indent=2))
