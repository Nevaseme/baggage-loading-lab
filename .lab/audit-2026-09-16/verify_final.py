import hashlib, json, re, zipfile
from pathlib import Path
from urllib.parse import unquote
root = Path.cwd()
files = [root / x for x in ('AGENTS.md','README.md','START_HERE.md','contracts/agent-interface.md','docs/README.md','docs/development.md','docs/evaluation-contract.md','docs/registry-operations.md','docs/2026-09-16-astra-workspace-audit.md','knowledge/lessons/packing-evidence.md')]
files += list((root/'experiments').glob('README.md'))
for directory in (root/'experiments').iterdir():
    if directory.is_dir() and directory.name != 'historical-shield':
        files += list(directory.glob('*.md'))
broken = []; checked = 0
for path in files:
    for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
        target = link.strip('<>').split('#')[0]
        if not target or re.match(r'^[a-zA-Z]+://',target): continue
        checked += 1
        if not (path.parent/unquote(target)).exists(): broken.append([str(path.relative_to(root)),link])
before = json.loads((root/'.lab/audit-2026-09-16/before.json').read_text())
changed = [name for name, expected in before['protected_files'].items() if not (root/name).is_file() or hashlib.sha256((root/name).read_bytes()).hexdigest() != expected]
archive = root/'.lab/exports/design-context-2026-09-16-astra.zip'
with zipfile.ZipFile(archive) as z:
    print('archive_integrity', z.testzip(), 'members',len(z.namelist()))
report = dict(active_files=len(files),local_links=checked,broken=broken,protected_files=len(before['protected_files']),protected_changed=changed,context_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
(root/'.lab/audit-2026-09-16/final-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
assert not broken and not changed
