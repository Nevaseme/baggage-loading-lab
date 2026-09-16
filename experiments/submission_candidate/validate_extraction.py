"""Run serial, strict physics checks against the frozen ZIP extraction."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'experiments/submission_candidate/validation'
AGENT = ROOT / 'deliverables/2026-09-16-support-recovery-packing/verified-extraction/support_recovery_packing/agent.py'
CASES = [
    ('c-original', 'C', 42, []),
    ('c-shuffle17', 'C', 17, ['--shuffle']),
    ('c-two-containers', 'C', 42, ['--config', 'experiments/validation_cases/two_containers.json']),
    ('b-shuffle17', 'B', 17, ['--shuffle']),
    ('b-lookahead3', 'B', 42, ['--config', 'experiments/validation_cases/lookahead3.json']),
    ('b-lookahead40', 'B', 42, ['--config', 'experiments/validation_cases/lookahead40.json']),
]

if __name__ == '__main__':
    for name, mode, seed, extra in CASES:
        output = OUT / (name + '.json')
        if output.exists():
            raise FileExistsError(output)
        command = [sys.executable, '-m', 'tools.benchmark', '--agent', str(AGENT),
                   '--task', '001', '--mode', mode, '--seed', str(seed),
                   '--output', str(output), *extra]
        with output.with_suffix('.log').open('w') as log:
            completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if not output.exists():
            raise RuntimeError(f'{name} produced no record; exit {completed.returncode}')
        result = json.loads(output.read_text())
        print(json.dumps({'case': name, **{key: result.get(key) for key in
              ('outcome', 'safe_placements', 'evaluation', 'policy_time_seconds', 'error')}}), flush=True)
