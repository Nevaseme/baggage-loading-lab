import hashlib, json, sys, time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from tools.benchmark import load_agent, json_default, source_hashes, deadline

source = root/'experiments/native_candidate_packing/variants/progressive_recovery/agent.py'
snapshot = root/'experiments/native_candidate_packing/results/progressive-historical-queries384-c-task001-seed42.snapshot.json'
trials = []
for limit in (96, 512):
    agent = load_agent(source)(str(source.parent))
    agent.shortlist_limit = limit
    agent.max_authorizations = 384
    started = time.perf_counter()
    row = {'shortlist_limit': limit, 'max_authorizations': 384}
    try:
        with deadline(8):
            row['action'] = agent.policy(json.loads(snapshot.read_text()))
        row['outcome'] = 'returned'
    except Exception as error:
        row.update(outcome=type(error).__name__, error=str(error))
    row['seconds'] = time.perf_counter()-started
    row['diagnostics'] = agent.last_diagnostics
    trials.append(row)
    for validator in agent._native.values():
        validator.close()
    if agent._preview is not None:
        agent._preview.close()

output = root/'experiments/native_candidate_packing/probes/c23-wide-selection.json'
output.write_text(json.dumps({'source_hashes': source_hashes(source.parent),
    'snapshot_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
    'timing_contended': True, 'trials': trials}, default=json_default, indent=2)+'\n')
print(json.dumps([{'limit': row['shortlist_limit'], 'outcome': row['outcome'],
                  'seconds': row['seconds'], 'queries': row['diagnostics']['authorizations']}
                 for row in trials]))

