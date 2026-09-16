"""Package the current candidate and run two tiny official lifecycle smoke cases.

Run with the Python environment containing the repository's runtime dependencies.
This checks cloud portability and ZIP loading; it does not measure a full score.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'support_recovery_packing'
sys.path.insert(0, str(ROOT))
from tools.package_agent import build_package


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tiny_tasks(sample: dict) -> tuple[dict, dict]:
    selected, modes = {}, {}
    for mode, optimize in (('A', True), ('B', False)):
        matches = [(key, value) for key, value in sample.items()
                   if value['agent']['optimize'] is optimize]
        if not matches:
            raise ValueError(f'Official sample contains no mode {mode} task')
        key, task = matches[0]
        task = copy.deepcopy(task)
        items = task['item_stream']['item_list'][:2]
        if len(items) != 2:
            raise ValueError(f'Sample task {key} must contain at least two items')
        task['item_stream']['item_list'] = items
        task['item_stream']['visible_pool'] = []
        task['visualizer']['vis'] = False
        selected[key], modes[key] = task, mode
    return selected, modes


def verify_extraction(extracted: Path, manifest: dict) -> None:
    package = extracted / PACKAGE
    actual = {path.relative_to(package).as_posix(): sha256(path)
              for path in package.rglob('*.py')}
    if actual != manifest['source_sha256']:
        raise RuntimeError('Extracted Python source hashes differ from the packaged source')
    embedded = json.loads((package / 'PACKAGE.json').read_text(encoding='utf-8'))
    if embedded['source_sha256'] != actual or embedded['package_name'] != PACKAGE:
        raise RuntimeError('Embedded package manifest does not match extracted source')


def validate_results(results: dict, tasks: dict) -> None:
    if set(results) != set(tasks):
        raise RuntimeError('Official runner did not return both expected smoke tasks')
    for task_id, task in tasks.items():
        row = results[task_id]
        evaluation = row.get('evaluation')
        if row.get('status') != 'success' or not isinstance(evaluation, dict):
            raise RuntimeError(f'{task_id}: official task failed or evaluation is null')
        ratio = evaluation.get('num_placed_items')
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isclose(ratio, 1., abs_tol=1e-12):
            raise RuntimeError(f'{task_id}: smoke did not place all two items ({ratio!r})')
        states = row.get('place_states', {})
        if not all(states.get(name) is True for name in ('is_included', 'is_valid', 'is_placed_safe')):
            raise RuntimeError(f'{task_id}: final placement predicates failed: {states!r}')
        for method, limit in (('policy', 'policy_timeout'), ('optimization', 'optimization_timeout')):
            elapsed = row.get('time_results', {}).get(method)
            if not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
                raise RuntimeError(f'{task_id}: invalid {method} timing')
            if elapsed > task['agent'][limit]:
                raise RuntimeError(f'{task_id}: {method} exceeded the official configured limit')


def run(output: Path) -> dict:
    output = (ROOT / output).resolve() if not output.is_absolute() else output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    report = dict(schema_version=1, kind='two_item_official_lifecycle_smoke',
                  full_score_evaluation=False, public_score=None, status='failed',
                  python=sys.version, executable=sys.executable, platform=platform.platform(),
                  dependencies={}, script_sha256=sha256(Path(__file__)))
    try:
        for name in ('numpy', 'gymnasium', 'pybullet', 'pillow'):
            report['dependencies'][name] = importlib.metadata.version(name)
        source = ROOT / 'experiments/submission_candidate/source'
        archive_path = output / 'agent.zip'
        package = build_package(source, PACKAGE, archive_path)
        report['package'] = package
        extracted = output / 'extracted'
        extracted.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                if not (extracted / entry.filename).resolve().is_relative_to(extracted):
                    raise RuntimeError('Archive member escapes its extraction directory')
            archive.extractall(extracted)
        verify_extraction(extracted, package)
        report['extracted_source_verified'] = True
        sample_path = ROOT / 'simulator/configs/sample_config.json'
        tasks, modes = tiny_tasks(json.loads(sample_path.read_text(encoding='utf-8')))
        config_path = output / 'smoke-config.json'
        config_path.write_text(json.dumps(tasks, indent=2) + '\n', encoding='utf-8')
        report.update(sample_config_sha256=sha256(sample_path), config_sha256=sha256(config_path),
                      task_modes=modes, items_per_task=2,
                      limits={key: {name: task['agent'].get(name) for name in
                              ('init_timeout', 'optimization_timeout', 'policy_timeout', 'max_mem')}
                              for key, task in tasks.items()})
        process_timeout = 60 + sum(float(task['agent']['init_timeout']) +
            (float(task['agent']['optimization_timeout']) if task['agent']['optimize'] else 0.) +
            2 * float(task['agent']['policy_timeout']) for task in tasks.values())
        report['process_timeout_seconds'] = process_timeout
        command = [sys.executable, '-m', 'scripts.run_test', '--config-path', str(config_path),
                   '--module-path', PACKAGE + '/', '--result-dir', str(output),
                   '--result-fname', 'official-results.json']
        environment = os.environ.copy()
        # Do not inherit host-specific test_deps or repository source paths.
        environment['PYTHONPATH'] = str(extracted)
        environment['PYTHONNOUSERSITE'] = '1'
        environment['OPENBLAS_NUM_THREADS'] = '1'
        environment['OMP_NUM_THREADS'] = '1'
        report['child_environment'] = {key: environment[key] for key in
            ('PYTHONPATH', 'PYTHONNOUSERSITE', 'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS')}
        with (output / 'official-run.log').open('w', encoding='utf-8') as log:
            completed = subprocess.run(command, cwd=ROOT / 'simulator', env=environment,
                                       stdout=log, stderr=subprocess.STDOUT, timeout=process_timeout, check=False)
        report['runner_exit_code'] = completed.returncode
        if completed.returncode:
            raise RuntimeError(f'Official runner exited with code {completed.returncode}; see official-run.log')
        result_path = output / 'official-results.json'
        results = json.loads(result_path.read_text(encoding='utf-8'))
        report['official_results'] = results
        validate_results(results, tasks)
        verify_extraction(extracted, package)
        if sha256(archive_path) != package['sha256']:
            raise RuntimeError('Archive changed during the official smoke run')
        report.update(status='passed', result_sha256=sha256(result_path))
    except Exception as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        report['elapsed_seconds'] = time.perf_counter() - started
        (output / 'smoke-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='Fresh output directory; relative paths resolve from the repository root')
    args = parser.parse_args()
    try:
        report = run(args.output)
    except FileExistsError:
        parser.error('Output already exists; choose a fresh directory')
    print(json.dumps({'status': report['status'], 'kind': report['kind'],
                      'public_score': None, 'error': report.get('error')}, sort_keys=True))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
