"""Inventory shareable project bytes; report credential-like matches by path only."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'knowledge/sync/2026-09-16-workspace-inventory.json'
raw = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
paths = sorted(set(value.decode('utf-8') for value in raw.split(b'\0') if value))
groups = defaultdict(lambda: {'files': 0, 'bytes': 0})
files = {}
large = []
suspect = []
patterns = [rb'(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}', rb'github_pat_[A-Za-z0-9_]{50,}',
            rb'(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{30,}', rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
for name in paths:
    path = ROOT / name
    if not path.is_file() or path == OUTPUT:
        continue
    data = path.read_bytes()
    files[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    group = name.split('/')[0] if '/' in name else '(root files)'
    groups[group]['files'] += 1
    groups[group]['bytes'] += len(data)
    if len(data) > 90 * 1024 * 1024:
        large.append(name)
    if any(re.search(pattern, data) for pattern in patterns):
        suspect.append(name)
report = {'scope': 'All tracked and non-ignored project files; inventory itself excluded.',
          'hash_scope': 'Local worktree bytes. Git may normalize documentation/tooling line endings per .gitattributes; raw evidence directories use -text.',
          'file_count': len(files), 'total_bytes': sum(row['bytes'] for row in files.values()),
          'groups': dict(groups), 'over_90_mib': large, 'credential_pattern_paths': suspect,
          'exclusions': '.gitignore; installed dependencies/runtimes, duplicate checkouts/exports, caches, authentication.',
          'files': files}
OUTPUT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: value for key, value in report.items() if key != 'files'}))
assert not large, 'Large files require separate asset storage'
assert not suspect, 'Inspect credential-shaped content before upload'
