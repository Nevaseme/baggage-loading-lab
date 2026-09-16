import json
from pathlib import Path
for name in ('fair_candidate_packing', 'native_candidate_packing', 'offline_settling_plan', 'controlled_drop_recovery'):
    root = Path('experiments') / name
    rows = []
    for path in sorted((root / 'results').glob('*.json')):
        result = json.loads(path.read_text())
        if 'records' not in result:
            continue
        count = len(result['config']['item_stream']['item_list'])
        fill = result.get('evaluation', {}).get('fill_score')
        fill_text = f'{fill:.3f}' if fill is not None else 'unavailable'
        maximum = result.get('policy_time_seconds', {}).get('max')
        time_text = f'{maximum:.3f}' if maximum is not None else 'unavailable'
        rows.append(f"| [{path.stem}](results/{path.name}) | {result['mode']} | {result['safe_placements']}/{count} | {fill_text} | {time_text} | {result['outcome']} |")
    (root / 'RESULTS.md').write_text('# Physics comparisons\n\nLocal proxies; Public score is not inferred. Each JSON records exact source/settings, configuration, stream, actions, outcome, and timings. A nonzero runner exit preserves physical failures and candidate exhaustion.\n\n| Run | Mode | Safe placements | Fill | Policy max (s) | Outcome |\n| --- | --- | ---: | ---: | ---: | --- |\n' + '\n'.join(rows) + '\n')
    print(name, len(rows))
