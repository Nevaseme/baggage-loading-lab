"""Upload the authorized submission assets using configured Git credentials.

Credentials remain in memory and are never included in output or saved records.
Run after the project commit has been pushed.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
REPO = 'Nevaseme/baggage-loading-lab'
ARTIFACT = 'artifact-40da95f00f099605fd9eeaa9abf211fa70e2b1b4f17a85ebb2b8a14f85a07e90'
BUNDLE = ROOT / 'deliverables/2026-09-16-support-recovery-packing'
API = 'https://api.github.com/repos/' + REPO


def git(*args):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), *args], cwd=ROOT, text=True).strip()


if __name__ == '__main__':
    filled = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                            capture_output=True, text=True, check=True)
    credential = dict(line.split('=', 1) for line in filled.stdout.splitlines() if '=' in line)
    token = credential['password']

    def request(url, method='GET', data=None, content_type='application/json'):
        host = urllib.parse.urlsplit(url).hostname
        assert host in ('api.github.com', 'uploads.github.com')
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                   'User-Agent': 'baggage-loading-lab', 'Content-Type': content_type}
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=120) as response:
            return json.load(response)

    assert request(API)['private'] is True
    commit = git('rev-parse', 'HEAD')
    remote = git('ls-remote', 'origin', 'refs/heads/main').split()[0]
    assert commit == remote, 'Push the exact project commit before creating its release'
    try:
        release = request(API + '/releases/tags/' + ARTIFACT)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise RuntimeError('Release lookup failed with HTTP ' + str(error.code)) from None
        body = {'tag_name': ARTIFACT, 'target_commitish': commit,
                'name': 'Support recovery packing: submitted ZIP and result',
                'body': 'Exact submitted archive and user-provided feedback. The result reports early termination; Public aggregate score is absent. See deliverables/2026-09-16-support-recovery-packing/ and docs/ai-handoff.md in the repository.',
                'draft': False, 'prerelease': False}
        release = request(API + '/releases', 'POST', json.dumps(body).encode())
    existing = {asset['name']: asset for asset in release['assets']}
    files = [BUNDLE / 'support-recovery-packing-2026-09-16.zip', BUNDLE / 'result-log.txt',
             ROOT / 'artifacts' / ARTIFACT / 'manifest.json']
    verified = []
    for path in files:
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        asset = existing.get(path.name)
        if asset is None:
            url = release['upload_url'].split('{')[0] + '?name=' + urllib.parse.quote(path.name)
            asset = request(url, 'POST', payload, 'application/octet-stream')
        assert asset.get('digest') == 'sha256:' + digest, 'Remote asset digest mismatch: ' + path.name
        verified.append({'name': path.name, 'sha256': digest, 'bytes': len(payload),
                         'url': asset['browser_download_url'], 'remote_digest': asset['digest']})
    record = {'repository': REPO, 'visibility': 'private', 'project_commit': commit,
              'release_url': release['html_url'], 'assets': verified,
              'verification': 'GitHub asset SHA-256 equals local bytes; main ref equals project commit.'}
    output = ROOT / 'knowledge/sync/2026-09-16-support-recovery-submission.json'
    output.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record))
