"""Root-owned real-data acceptance; original submissions are read-only inputs."""
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.lab.registry import Registry

# Replay mutations only in an isolated copy. Real records are read-only here.
scratch = tempfile.TemporaryDirectory(prefix='migration-replay-', dir=ROOT / '.lab')
replay_root = Path(scratch.name)
for directory in ('artifacts', 'evaluations'):
    shutil.copytree(ROOT / directory, replay_root / directory)
registry = Registry(replay_root)
entries = [
    ('guarded_extreme_point_beam', 'artifact-3789b037da39bd2f38215d711c42ad9cf504503f44b94016517a675044cb4a54', 'submit/highscore_guarded_20260813_score12.6/result-log.txt', '12.622949582873819', None, 'simulator/submissions/highscore_guarded_20260813.zip'),
    ('conservative_extreme_point_packing', 'source-b6f7748093a98062bb7be085ee6b91276cabeb5d2411ebbc902b26e57d635ddc', 'submit/Conservative Extreme-Point Packing_score29.7/result-log.txt', '29.74350010538', None, 'submit/Conservative Extreme-Point Packing_score29.7/high_score'),
    ('ingress_preserving_column_scaffold', 'source-299def2d0317271a2133ce257c3992c46924ee09340713439de06701c5bbc0c8', 'submit/ingress_preserving_column_scaffold/result-log.txt', None, None, '.lab/migration-source/ingress_preserving_column_scaffold'),
    ('surface_frontier_extreme_backfill', 'source-53a43e157ddbe6aaf783385204d7c4fe232f68e10d2c83a98b896ca140e83b2c', 'submit/surface_frontier_extreme_backfill_score11/result-log.txt', None, '11', '.lab/migration-source/surface_frontier_extreme_backfill'),
]
receipt = []
for name, artifact_id, result_path, public, rounded, source in entries:
    if artifact_id.startswith('artifact-'):
        repeated = registry.ingest(ROOT / source, name)
    else:
        repeated = registry.import_source(ROOT / source, name)
    assert repeated['artifact_id'] == artifact_id and repeated['deduplicated']
    evaluation = registry.record(artifact_id, ROOT / result_path, public_score=public, rounded_public=rounded)
    assert evaluation['deduplicated']
    record = json.loads((Path(evaluation['path']) / 'record.json').read_text(encoding='utf-8'))
    raw = replay_root / record['evidence_refs'][0]['path']
    assert raw.read_bytes() == (ROOT / result_path).read_bytes()
    assert record['public_score'] == public and record['rounded_public'] == rounded
    assert record['status_normalized'] == 'stopped'
    original = json.loads(raw.read_text(encoding='utf-8'), parse_float=str, parse_int=str)
    assert record['metrics'] == {key: original[key] for key in record['metrics']}
    receipt.append({'algorithm_name': name, 'artifact_id': artifact_id, 'evaluation_id': record['evaluation_id'], 'original_result_path': result_path, 'raw_sha256': hashlib.sha256(raw.read_bytes()).hexdigest(), 'public_score': public, 'rounded_public': rounded, 'status': record['status_normalized'], 'metrics': record['metrics'], 'retry_deduplicated': True})

guarded = ROOT / entries[0][5]
with zipfile.ZipFile(guarded) as archive:
    members = [member for member in archive.infolist() if not member.is_dir()]
    for member in members:
        saved = ROOT / 'submit/highscore_guarded_20260813_score12.6' / member.filename
        imported = ROOT / 'artifacts' / entries[0][1] / 'source' / member.filename
        assert saved.read_bytes() == imported.read_bytes() == archive.read(member)
assert len(members) == 10

registry.render()
validation = registry.validate()
assert validation['valid'], validation
assert len(list((ROOT / 'artifacts').glob('*/manifest.json'))) == 4
assert len(list((ROOT / 'evaluations').glob('*/record.json'))) == 4
print(json.dumps({'date': '2026-09-08', 'registry_revision': validation['registry_revision'], 'real_artifacts': 4, 'real_evaluations': 4, 'guarded_original_zip_sha256': hashlib.sha256(guarded.read_bytes()).hexdigest(), 'guarded_exact_payload_matches': 10, 'original_archives_missing': 3, 'records': receipt}, ensure_ascii=False, indent=2))
scratch.cleanup()
