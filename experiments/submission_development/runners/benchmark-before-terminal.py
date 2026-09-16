"""Run a supplied Agent against official physics; persist episode outcomes and identity.

Linux is required for per-call deadlines. Results are local proxies, not Public scores.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager, redirect_stdout
import copy
import hashlib
import importlib.util
import importlib.metadata
import json
from pathlib import Path
import platform
import random
import signal
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]


def configure_task(task, mode, items, seed, shuffle):
    config = copy.deepcopy(task)
    stream = config['item_stream']
    if items is not None:
        if items < 1:
            raise ValueError('items must be positive')
        stream['item_list'] = stream['item_list'][:items]
    if shuffle:
        random.Random(seed).shuffle(stream['item_list'])
    config['agent']['optimize'] = mode == 'A'
    if mode == 'B':
        stream['look_ahead'] = min(40, max(3, stream['look_ahead']))
    elif mode == 'C':
        stream['look_ahead'] = 1
    stream['max_space'] = min(stream['max_space'], stream['look_ahead'])
    config['visualizer']['vis'] = False
    return config


def valid_order(actual, expected):
    return (isinstance(actual, list) and all(type(x) is int for x in actual)
            and Counter(actual) == Counter(expected))


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def source_hashes(directory):
    return {p.relative_to(directory).as_posix(): digest(p.read_bytes())
            for p in sorted(directory.rglob('*')) if p.is_file()
            and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')}


def layout_summary(containers):
    """Report cargo CoG and raw volume; neither substitutes for the fill scorer."""
    rows = []
    for container in containers:
        items = container.get('packed_items', [])
        mass = sum(float(item['mass']) for item in items)
        cog = ([sum(float(item['mass']) * float(item['pos'][axis]) for item in items) / mass
                for axis in range(3)] if mass else None)
        local = cog.copy() if cog else None
        if local:
            local[0] -= float(container.get('center', [0, 0, 0])[0])
        rows.append({'container_index': container['index'], 'packed_count': len(items),
                     'cargo_mass': mass, 'mass_weighted_cog_world': cog,
                     'mass_weighted_cog_local': local,
                     'raw_packed_volume': sum(float(item['length']) * float(item['width']) *
                                              float(item['height']) for item in items)})
    return rows


def finish_environment(environment, record):
    for stage, operation in [('evaluation', environment.evaluate), ('close', environment.close)]:
        try:
            value = operation()
            if stage == 'evaluation':
                record['evaluation'] = value
        except Exception as error:
            record[stage + '_error'] = {'type': type(error).__name__, 'message': str(error)}
            if record.get('outcome') == 'completed':
                record['outcome'] = stage + '_error'


@contextmanager
def deadline(seconds):
    def expired(_signum, _frame):
        raise TimeoutError(f'call exceeded {seconds:g} seconds')
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def load_agent(path):
    package_name = 'benchmark_candidate_' + digest(str(path).encode())[:12]
    package = types.ModuleType(package_name)
    package.__path__ = [str(path.parent)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(package_name + '.agent', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.Agent


def run(args):
    import numpy as np
    sys.path.insert(0, str(ROOT / 'simulator'))
    from src.ground_handling.env import GroundHandlingEnv

    source = Path(args.agent).resolve()
    agent_options = json.loads(Path(args.settings).read_text()) if args.settings else {}
    if not isinstance(agent_options, dict):
        raise ValueError('agent settings must be a JSON object')
    config = configure_task(json.loads(Path(args.config).read_text())[args.task],
                            args.mode, args.items, args.seed, args.shuffle)
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError(f'use a new output path: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {'task': args.task, 'mode': args.mode, 'seed': args.seed,
              'shuffled': args.shuffle, 'config': config,
              'config_sha256': digest(json.dumps(config, sort_keys=True).encode()),
              'source': str(source), 'source_hashes': source_hashes(source.parent),
              'runner_sha256': digest(Path(__file__).read_bytes()),
              'simulator_hashes': source_hashes(ROOT / 'simulator/src/ground_handling'),
              'host': platform.platform(), 'python': sys.version,
              'outcome': 'initialization_error', 'safe_placements': 0, 'records': [],
              'policy_seconds': [], 'optimized_order': None, 'public_score': None}
    record['execution_mode'] = 'strict_in_process_physics_diagnostic'
    record['agent_options'] = agent_options
    record['applied_deadlines_seconds'] = {'initialization': 10, 'optimization': 180,
                                          'policy': args.policy_seconds}
    record['dependencies'] = {name: importlib.metadata.version(name)
                              for name in ('numpy', 'gymnasium', 'pybullet', 'pillow')}
    environment = None
    observation = None
    agent = None
    started = time.perf_counter()
    stage = 'initialization'
    # Preserve simulator output without flooding the console or discarding diagnostics.
    with output.with_suffix('.log').open('w') as log, redirect_stdout(log):
        try:
            random.seed(args.seed)
            np.random.seed(args.seed)
            environment = GroundHandlingEnv(config, verbose=False)
            environment.reset_settings()
            environment.reset_item_stream()
            init_started = time.perf_counter()
            with deadline(10):
                agent = load_agent(source)(str(source.parent) + '/')
                for name, value in agent_options.items():
                    if name.startswith('_') or not hasattr(agent, name) or callable(getattr(agent, name)):
                        raise ValueError(f'unknown or non-configurable Agent setting: {name}')
                    setattr(agent, name, value)
                if not agent.get_init_states(environment.get_init_states()):
                    raise ValueError('get_init_states returned false')
            record['initialization_seconds'] = time.perf_counter() - init_started
            if args.mode == 'A':
                stage = 'optimization'
                optimization_started = time.perf_counter()
                with deadline(180):
                    order = agent.optimize(environment.get_info_for_optimization())
                record['optimization_seconds'] = time.perf_counter() - optimization_started
                record['optimization_diagnostics'] = copy.deepcopy(getattr(agent, 'last_plan_stats', None))
                if not valid_order(order, [i['index'] for i in config['item_stream']['item_list']]):
                    raise ValueError('optimization must return a complete permutation')
                record['optimized_order'] = order
                environment.set_item_order(order)
                environment.reset_item_stream()
            observation, _ = environment.reset(seed=args.seed)
            count = len(config['item_stream']['item_list'])
            for step in range(count):
                observation['depth_map'] = environment.shm_depth_map.copy()
                # Snapshot before calling policy, which may update its input.
                snapshot = copy.deepcopy(observation)
                stage = 'policy'
                policy_started = time.perf_counter()
                try:
                    with deadline(args.policy_seconds):
                        action = agent.policy(observation)
                finally:
                    record['policy_seconds'].append(time.perf_counter() - policy_started)
                if record['policy_seconds'][-1] > args.policy_seconds:
                    raise TimeoutError('policy returned after its deadline')
                stage = 'physics'
                next_observation, _, terminated, truncated, info = environment.step(action)
                status = info.get('status', {})
                row = {'step': step, 'action': action, 'status': status,
                       'policy_seconds': record['policy_seconds'][-1],
                       'terminated': terminated, 'truncated': truncated}
                diagnostics = getattr(agent, 'last_diagnostics', getattr(agent, 'last_search_stats', None))
                if diagnostics is not None:
                    row['search'] = copy.deepcopy(diagnostics)
                record['records'].append(row)
                safe = all(status.get(k) is True for k in
                           ('is_included', 'is_valid', 'is_placed_safe'))
                if not safe:
                    record['outcome'] = 'physical_failure'
                    record['first_failure_step'] = step
                    record['first_failure_status'] = status
                    observation = snapshot
                    break
                record['safe_placements'] += 1
                observation = next_observation
                if terminated or truncated:
                    record['outcome'] = ('completed' if record['safe_placements'] == count
                                         and not truncated else 'early_termination')
                    break
            else:
                record['outcome'] = 'step_limit'
        except Exception as error:
            record['outcome'] = stage + ('_timeout' if isinstance(error, TimeoutError) else '_error')
            record['error'] = {'type': type(error).__name__, 'message': str(error)}
            if 'snapshot' in locals():
                observation = snapshot
        finally:
            if agent is not None:
                if hasattr(agent, 'last_plan_stats'):
                    record['optimization_diagnostics'] = copy.deepcopy(agent.last_plan_stats)
                record['last_search_stats'] = getattr(agent, 'last_diagnostics',
                                                     getattr(agent, 'last_search_stats', None))
            if environment is not None:
                try:
                    record['final_containers'] = environment.container_manager.get_item_info_in_containers()
                    record['layout_proxies'] = layout_summary(record['final_containers'])
                except Exception as error:
                    record['layout_error'] = {'type': type(error).__name__, 'message': str(error)}
                finish_environment(environment, record)
            if record['outcome'] != 'completed' and observation is not None:
                state = {k: v for k, v in observation.items() if k != 'depth_map'}
                output.with_suffix('.snapshot.json').write_text(json.dumps(state, default=json_default))
            values = np.asarray(record['policy_seconds'])
            record['policy_time_seconds'] = ({'count': len(values), 'max': float(values.max()),
                **{f'p{q}': float(np.percentile(values, q)) for q in (50, 95, 99)}} if len(values) else {})
            record['elapsed_seconds'] = time.perf_counter() - started
            output.write_text(json.dumps(record, default=json_default, indent=2) + '\n')
    return record


def json_default(value):
    if hasattr(value, 'tolist'):
        return value.tolist()
    raise TypeError(type(value).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', required=True)
    parser.add_argument('--settings', help='JSON file of Agent options for a controlled ablation')
    parser.add_argument('--config', default=str(ROOT / 'simulator/configs/sample_config.json'))
    parser.add_argument('--task', choices=['000', '001'], required=True)
    parser.add_argument('--mode', choices=['A', 'B', 'C'], required=True)
    parser.add_argument('--items', type=int)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--shuffle', action='store_true')
    parser.add_argument('--policy-seconds', type=float, default=8)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({k: result.get(k) for k in ('source', 'task', 'mode', 'seed', 'outcome',
                    'safe_placements', 'evaluation', 'policy_time_seconds', 'error')}))
    return 0 if result['outcome'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
