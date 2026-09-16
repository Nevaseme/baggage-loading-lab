"""Check a produced portable bundle without executing its source."""
import hashlib
import json
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

bundle = Path(sys.argv[1])
expected_commit = sys.argv[2]
with zipfile.ZipFile(bundle) as archive:
    names = set(archive.namelist())
    hashes = json.loads(archive.read('FILE_HASHES.json'))['files']
    assert set(hashes) == names - {'FILE_HASHES.json'}
    for name, digest in hashes.items():
        assert hashlib.sha256(archive.read(name)).hexdigest() == digest, name
    registry = json.loads(archive.read('REGISTRY.json'))
    assert registry['source_commit'] == expected_commit
    assert len(registry['artifact_ids']) == len(registry['evaluation_ids']) == 4
    required = {'START_HERE.md', 'AGENTS.md', 'README.md', 'progress.md', 'knowledge/CURRENT.md', 'knowledge/lessons/packing-evidence.md', 'contracts/agent-interface.md', 'docs/evaluation-contract.md', 'docs/registry-operations.md', 'docs/README.md'}
    assert required <= names
    assert not any(part in {'.git', '.lab', '__pycache__'} for name in names for part in name.split('/'))
    link_sources = required | {name for name in names if name.endswith('/algorithm.md')}
    for name in link_sources:
        for target in re.findall(r'\]\(([^)]+)\)', archive.read(name).decode('utf-8')):
            target = target.strip('<>')
            if urlsplit(target).scheme or target.startswith('#'):
                continue
            path = unquote(target.split('#')[0])
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
            assert resolved in names or any(entry.startswith(resolved.rstrip('/') + '/') for entry in names), (name, target)
print(json.dumps({'bundle': str(bundle.resolve()), 'sha256': hashlib.sha256(bundle.read_bytes()).hexdigest(), 'file_count': len(names), 'source_commit': expected_commit, 'registry_revision': registry['registry_revision'], 'file_hash_closure': True, 'required_guidance_links': True, 'artifact_count': 4, 'evaluation_count': 4}, indent=2))
