"""Verify submitted bytes, extraction, and official lifecycle results."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / 'deliverables/2026-09-16-support-recovery-packing/support-recovery-packing-2026-09-16.zip'
EXTRACTED = ROOT / 'deliverables/2026-09-16-support-recovery-packing/verified-extraction/support_recovery_packing'
OUT = ROOT / 'experiments/submission_candidate/validation'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == '__main__':
    expected = '40da95f00f099605fd9eeaa9abf211fa70e2b1b4f17a85ebb2b8a14f85a07e90'
    assert sha(ARCHIVE) == expected
    manifest = json.loads((EXTRACTED / 'PACKAGE.json').read_text())
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 10
        for name, digest in manifest['source_sha256'].items():
            assert sha(EXTRACTED / name) == digest
            assert sha(ROOT / 'experiments/submission_candidate/source' / name) == digest
            assert archive.read('support_recovery_packing/' + name) == (EXTRACTED / name).read_bytes()
    official = json.loads((OUT / 'official-samples.json').read_text())
    assert set(official) == {'000', '001'}, official
    for name, result in official.items():
        assert result['status'] == 'success' and result['evaluation'] is not None, result
        assert result['time_results']['policy'] < 8, result
        assert result['time_results']['optimization'] < 180, result
    strict_results = {}
    for name in ['c-original', 'c-shuffle17', 'c-two-containers', 'b-shuffle17',
                 'b-lookahead3', 'b-lookahead40']:
        result = json.loads((OUT / (name + '.json')).read_text())
        assert result['outcome'] in ('completed', 'terminal_rejection'), result['outcome']
        assert result.get('error') is None
        assert result['policy_time_seconds']['max'] < 8
        for source_name, digest in manifest['source_sha256'].items():
            assert result['source_hashes'][source_name] == digest
        assert all(all(row['status'][key] for key in ['is_included', 'is_valid', 'is_placed_safe'])
                   for row in result['records'][:result['safe_placements']])
        strict_results[name] = {'sha256': sha(OUT / (name + '.json')),
                                'outcome': result['outcome'], 'safe_count': result['safe_placements']}
    prior_path = ROOT / 'experiments/native_candidate_packing/results/progressive-historical-queries384-c-task001-seed42.json'
    prior = json.loads(prior_path.read_text())
    current = json.loads((OUT / 'c-original.json').read_text())
    assert [row['action'] for row in prior['records'][:23]] == [row['action'] for row in current['records'][:23]]
    record = {'archive_sha256': expected, 'archive_bytes': ARCHIVE.stat().st_size,
              'accepted_action_reproduction': {'mode': 'C', 'count': 23, 'matched': True,
                  'prior_record_sha256': sha(prior_path)},
              'source_sha256': manifest['source_sha256'], 'official_results': official,
              'strict_results': strict_results,
              'verification_inputs_sha256': {name: sha(ROOT / name) for name in
                  ['simulator/configs/sample_config.json', 'tools/benchmark.py',
                   'tools/package_agent.py', 'simulator/scripts/run_test.py',
                   'simulator/src/ground_handling/app.py', 'simulator/src/ground_handling/runner.py']}}
    (OUT / 'archive-verification.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))
