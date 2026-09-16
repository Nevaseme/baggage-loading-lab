import hashlib,json,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from tools.benchmark import load_agent,source_hashes,json_default,deadline
source=root/'experiments/native_candidate_packing/variants/progressive_recovery/agent.py'
Agent=load_agent(source)
h=sys.modules[Agent.__module__].h
original=Agent._prefilter
trials=[]
for name,rel in [('c23','experiments/native_candidate_packing/results/progressive-historical-queries384-c-task001-seed42.snapshot.json'),('b23','experiments/fair_candidate_packing/results/baseline-b-task001-seed42.snapshot.json'),('c16','experiments/native_candidate_packing/results/progressive-historical-queries384-c-task001-shuffle17.snapshot.json')]:
    path=root/rel
    def permissive(item,container,dims,center,packed,shelves):
        if not h._inside_container(container,center,dims,-.007) or not h._target_clear(center,dims,packed,shelves):
            return False,0.,h._floor_z(container)
        ratio,z=h._support_ratio(container,center,dims,packed)
        return ratio>=.5,ratio,z
    Agent._prefilter=staticmethod(permissive)
    agent=Agent(str(source.parent))
    agent.shortlist_limit=512; agent.max_authorizations=512; agent.policy_seconds=7.; agent.preview_search_seconds=3.; agent.max_candidate_checks=16000
    row=dict(state=name,snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),support_minimum=.5,center_support_required=False)
    started=time.perf_counter()
    try:
        with deadline(8): row['action']=agent.policy(json.loads(path.read_text()))
        row['outcome']='returned'
    except Exception as error: row.update(outcome=type(error).__name__,error=str(error))
    row.update(seconds=time.perf_counter()-started,diagnostics=agent.last_diagnostics)
    trials.append(row)
    print(name,row['outcome'],row['seconds'],flush=True)
    for validator in agent._native.values(): validator.close()
    if agent._preview is not None: agent._preview.close()
output=root/'experiments/submission_development/support-probe.json'
assert not output.exists()
output.write_text(json.dumps(dict(source_hashes=source_hashes(source.parent),probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),timing_contended=True,trials=trials),default=json_default,indent=2)+'\n')
