"""Summarize preserved benchmark records without relabeling local scores."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'experiments/submission_candidate/validation'

if __name__ == '__main__':
    rows = []
    hosts = set()
    for name in ['c-original', 'c-shuffle17', 'c-two-containers', 'b-shuffle17',
                 'b-lookahead3', 'b-lookahead40']:
        path = OUT / (name + '.json')
        record = json.loads(path.read_text())
        hosts.add(record['host'])
        rows.append({'case': name, 'outcome': record['outcome'],
                     'safe_count': record['safe_placements'],
                     'total_count': len(record['config']['item_stream']['item_list']),
                     'evaluation': record.get('evaluation'),
                     'policy_time_seconds': record['policy_time_seconds'],
                     'layout_proxies': record.get('layout_proxies'),
                     'first_failure_step': record.get('first_failure_step'),
                     'first_failure_status': record.get('first_failure_status'),
                     'error': record.get('error')})
    report = {'public_score': None, 'execution_hosts': sorted(hosts),
              'campaign': 'Six serial episodes; no extra warmup; frozen ZIP extraction; 8 s strict policy limit.',
              'cases': rows,
              'metrics_limits': ['CoG and fill are local proxies, not the Public aggregate.',
                  'Per-action support and displacement/rotation diagnostics are preview estimates.',
                  'Exact post-placement motion magnitudes and separate soft/priority scorer components are unavailable in these runner records.',
                  'The strict runner has no fallback; official sample logs show no timeout fallback.']}
    (OUT / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    text = ['# Exact-extraction validation', '',
            'Local proxies; Public score pending. All cases use task001 with 42 items.', '',
            '| Case | Safe | Fill | Policy p50/p95/p99/max (s) | Outcome |',
            '| --- | ---: | ---: | --- | --- |']
    for row in rows:
        times = row['policy_time_seconds']
        values = '/'.join(f'{times[key]:.3f}' for key in ['p50', 'p95', 'p99', 'max'])
        text.append(f"| [{row['case']}]({row['case']}.json) | {row['safe_count']}/{row['total_count']} | {row['evaluation']['fill_score']:.4f} | {values} | {row['outcome']} |")
    text += ['', 'No additional warmup; full episodes ran serially under an 8-second policy deadline.',
             'Terminal rejection is an early stop, not a successful placement.', '',
             'See [structured summary](summary.json) for layout proxies and metric limitations.', '']
    (OUT / 'README.md').write_text('\n'.join(text))
    print(json.dumps(report))
