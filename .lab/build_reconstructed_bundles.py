"""One-off historical evidence packaging; never imports candidate code."""
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
out = root / '.lab' / 'exports' / 'reconstructed-source-results-2026-09-09'
out.mkdir(parents=True, exist_ok=True)
folders = {
    'conservative_extreme_point_packing': 'Conservative Extreme-Point Packing_score29.7',
    'guarded_extreme_point_beam': 'highscore_guarded_20260813_score12.6',
    'ingress_preserving_column_scaffold': 'ingress_preserving_column_scaffold',
    'surface_frontier_extreme_backfill': 'surface_frontier_extreme_backfill_score11',
}
sha = lambda data: hashlib.sha256(data).hexdigest()
manifests = [json.loads(p.read_text(encoding='utf-8')) for p in (root/'artifacts').glob('*/manifest.json')]
evaluations = [json.loads(p.read_text(encoding='utf-8')) for p in (root/'evaluations').glob('*/record.json')]
receipt = {'kind': 'reconstructed_source_and_result_bundles', 'date': '2026-09-09',
           'not_original_submission_archives': True, 'new_evaluations_created': 0, 'bundles': []}
for name, folder in folders.items():
    base = root / 'submit' / folder
    manifest, = [m for m in manifests if m['algorithm_name'] == name]
    evaluation, = [e for e in evaluations if e['artifact_id'] == manifest['artifact_id']]
    payload = {}
    omitted = []
    for path in sorted(base.rglob('*')):
        assert not path.is_symlink(), path
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            omitted.append(relative)
            continue
        assert path.suffix == '.py' or relative == 'result-log.txt', relative
        payload[relative] = path.read_bytes()
    source_hashes = manifest['source_file_hashes']
    prefix = 'high_score/' if name == 'conservative_extreme_point_packing' else ''
    assert set(payload) - {'result-log.txt'} == {prefix+p for p in source_hashes}
    for relative, digest in source_hashes.items():
        data = payload[prefix+relative]
        assert sha(data) == digest
        assert data == (root/'artifacts'/manifest['artifact_id']/'source'/relative).read_bytes()
    raw_ref, = [r for r in evaluation['evidence_refs'] if r['kind'] == 'raw_result']
    assert payload['result-log.txt'] == (root/raw_ref['path']).read_bytes()
    assert sha(payload['result-log.txt']) == evaluation['raw_result_sha256']
    note = (f'# Reconstructed source and result evidence\n\nAlgorithm: {name}\n\n'
            'This ZIP was newly built from saved source and result-log.txt. It is NOT the original submitted ZIP, '
            'a new submission, or a physically validated submission package. Historical scores refer to the linked '
            'evaluation, not to this new ZIP byte stream. Original folder layout and payload bytes are preserved; '
            'Python caches are omitted. No algorithm code was executed.\n\n'
            f'Artifact: {manifest["artifact_id"]}\nEvaluation: {evaluation["evaluation_id"]}\n'
            f'Historical Public exact: {evaluation["public_score"]}\nHistorical Public rounded: {evaluation["rounded_public"]}\n')
    payload['RECONSTRUCTION.md'] = note.encode('utf-8')
    filename = name.replace('_', '-') + '-source-result-reconstructed.zip'
    target = out/filename
    assert not target.exists(), target
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for relative, data in sorted(payload.items()):
            info = zipfile.ZipInfo(relative, (1980,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, data)
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        assert set(z.namelist()) == set(payload)
        assert all(z.read(p) == b for p,b in payload.items())
    receipt['bundles'].append({'algorithm_name': name, 'filename': filename,
        'sha256': sha(target.read_bytes()), 'bytes': target.stat().st_size,
        'source_folder': 'submit/'+folder, 'artifact_id': manifest['artifact_id'],
        'evaluation_id': evaluation['evaluation_id'], 'historical_public_score': evaluation['public_score'],
        'historical_rounded_public': evaluation['rounded_public'],
        'raw_result_sha256': evaluation['raw_result_sha256'], 'omitted_cache_files': omitted,
        'files': {p: sha(b) for p,b in sorted(payload.items())}})
print(json.dumps(receipt, ensure_ascii=False, indent=2))
