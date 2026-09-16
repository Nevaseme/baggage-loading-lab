import hashlib,json,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
from tools.benchmark import load_agent,json_default,source_hashes
source=root/'experiments/motion_recovery/source/agent.py';Agent=load_agent(source)
package=Agent.__module__.rsplit('.',1)[0]
Motion=__import__(package+'.motion',fromlist=['MotionStatePreview']).MotionStatePreview
Native=__import__(package+'.native',fromlist=['NativeValidator']).NativeValidator
frame=json.loads((root/'experiments/motion_state_preview/sequential-carry.json').read_text())['trials'][21]['preview']
frame['_motion_frame']['states']={int(k):v for k,v in frame['_motion_frame']['states'].items()}
statepath=root/'experiments/native_candidate_packing/results/progressive-b-task001-seed42.snapshot.json';obs=json.loads(statepath.read_text())
record=json.loads((root/'experiments/motion_recovery/results/motion-drop-b-task001-seed42.json').read_text())
action=record['last_search_stats']['previews'][2]['action']
with Native(obs['container_list'][0]) as native:check=native.check(obs['pool_list'][action['item_idx']],action)
with Motion() as preview:
    preview.accept(frame)
    result=preview.evaluate(obs['container_list'][0],obs['pool_list'][action['item_idx']],action)
result.pop('_motion_frame',None)
output=root/'experiments/submission_development/diverse-release-probe.json';assert not output.exists()
output.write_text(json.dumps(dict(action=action,native=check,preview=result,source_hashes=source_hashes(source.parent),snapshot_sha256=hashlib.sha256(statepath.read_bytes()).hexdigest()),default=json_default,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('safe','steps','displacement','angle_degrees','lost_volume','seconds')}))
