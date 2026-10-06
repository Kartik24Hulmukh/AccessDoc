#!/usr/bin/env python3
"""One fixed diagnostic, not runtime policy or deadline acceptance."""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUDGET_NS = 30_000_000
QUANTUM_NS = 1_000_000
SAMPLES = 3
MAX_CALLS = 32
WATCHDOG_SECONDS = 8
MAX_JSON_BYTES = 512 * 1024
CONTROLLER_GATE_SECONDS = 1


MAX_FAILURE_RECORDS = 8
MAX_ERROR_TYPE_CHARS = 128
MAX_ERROR_MESSAGE_CHARS = 1024
MAX_ERROR_REPR_CHARS = 2048


def bounded_failure(exc, stage):
    kind = type(exc).__module__ + '.' + type(exc).__qualname__
    try:
        message = str(exc)
    except Exception:
        message = '<exception message unavailable>'
    try:
        representation = repr(exc)
    except Exception:
        representation = '<exception repr unavailable>'
    return {'stage': stage[:32], 'error_type': kind[:MAX_ERROR_TYPE_CHARS],
            'error_message': message[:MAX_ERROR_MESSAGE_CHARS],
            'error_repr': representation[:MAX_ERROR_REPR_CHARS],
            'type_truncated': len(kind) > MAX_ERROR_TYPE_CHARS,
            'message_truncated': len(message) > MAX_ERROR_MESSAGE_CHARS,
            'repr_truncated': len(representation) > MAX_ERROR_REPR_CHARS}


def failure_artifact_receipt(path):
    receipt = {'artifact_path': str(path), 'available': path.exists(),
               'failure_records': [], 'errors': []}
    if not receipt['available']:
        return receipt
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError('failure artifact exceeds bounded read cap')
        payload = json.loads(raw.decode('utf-8'))
        if not isinstance(payload, dict):
            raise ValueError('failure artifact is not an object')
        receipt['sha256'] = hashlib.sha256(raw).hexdigest()
        receipt['diagnostic_valid'] = payload.get('diagnostic_valid')
        receipt['incomplete'] = payload.get('incomplete')
        for record in payload.get('failure_records', [])[:MAX_FAILURE_RECORDS]:
            if isinstance(record, dict):
                receipt['failure_records'].append({
                    'stage': str(record.get('stage', ''))[:32],
                    'error_type': str(record.get('error_type', ''))[:MAX_ERROR_TYPE_CHARS],
                    'error_message': str(record.get('error_message', ''))[:MAX_ERROR_MESSAGE_CHARS],
                    'error_repr': str(record.get('error_repr', ''))[:MAX_ERROR_REPR_CHARS],
                    'type_truncated': bool(record.get('type_truncated', False)),
                    'message_truncated': bool(record.get('message_truncated', False)),
                    'repr_truncated': bool(record.get('repr_truncated', False))})
        receipt['errors'] = [str(error)[:MAX_ERROR_REPR_CHARS]
                             for error in payload.get('errors', [])[:MAX_FAILURE_RECORDS]]
    except Exception as exc:
        receipt['failure_records'] = [bounded_failure(exc, 'driver_artifact_read')]
        receipt['read_failed'] = True
    return receipt


def source_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def write_json(path, payload):
    data = json.dumps(payload, indent=2, allow_nan=False) + '\n'
    if len(data.encode('utf-8')) > MAX_JSON_BYTES:
        raise RuntimeError('artifact byte cap exceeded; no truncation')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(data, encoding='utf-8')
    os.replace(temporary, path)


def fixture(kind):
    if kind == 'lock':
        obj = threading.Lock()
        obj.acquire()
    elif kind == 'event':
        obj = threading.Event()
    else:
        obj = Future()
    condition = getattr(obj, '_cond', None) or getattr(obj, '_condition', None)
    state_lock = getattr(condition, '_lock', None) if condition is not None else None
    metadata = {'python_type': type(obj).__module__ + '.' + type(obj).__name__,
                'observed_internal_state_lock_type': None if state_lock is None else
                type(state_lock).__module__ + '.' + type(state_lock).__name__,
                'metadata_scope': 'Python types observed only; compiled native backend not inferred'}
    return obj, metadata


def complete(kind, obj):
    if kind == 'lock':
        obj.release()
    elif kind == 'event':
        obj.set()
    else:
        obj.set_result('fixed-completion')


def one_wait(kind, obj, timeout):
    if kind == 'lock':
        return obj.acquire(timeout=timeout), None
    if kind == 'event':
        return obj.wait(timeout=timeout), None
    try:
        value = obj.result(timeout=timeout)
        return True, value
    except FutureTimeout:
        return False, None


def run_child(output):
    plan = []
    for kind in ('lock', 'event', 'future'):
        for scenario in ('held', 'completion'):
            for sample in range(SAMPLES):
                for mode in ('full', 'quantum'):
                    obj, metadata = fixture(kind)
                    plan.append({'kind': kind, 'scenario': scenario, 'sample': sample,
                                 'mode': mode, 'obj': obj, 'metadata': metadata,
                                 'go': threading.Event(), 'entered': threading.Event(),
                                 'done': threading.Event(), 'result': None})
    rows, errors, failure_records = [], [], []
    stop = threading.Event()
    clocks = {k: vars(time.get_clock_info(k)) for k in ('monotonic', 'perf_counter', 'thread_time')}
    info = sys.thread_info
    metadata = {'source_sha256': source_hash(), 'python': sys.version,
                'implementation': platform.python_implementation(), 'platform': platform.platform(),
                'clocks': clocks, 'sys_thread_info_observed': {'name': info.name, 'lock': info.lock, 'version': info.version},
                'backend_scope': 'actual Python APIs; no modern before-GIL/native backend timestamps or flags inferred',
                'switch_interval_observed_not_changed': sys.getswitchinterval(),
                'budget_ns': BUDGET_NS, 'quantum_ns': QUANTUM_NS,
                'samples_per_primitive_mode_scenario': SAMPLES, 'planned_trials': len(plan),
                'max_calls_per_trial': MAX_CALLS, 'one_serial_worker': True,
                'watchdog_seconds': WATCHDOG_SECONDS, 'max_json_bytes': MAX_JSON_BYTES,
                'fairness_measured': False, 'network_or_provider_calls': 0}
    partial = output.with_name(output.stem + '.partial.json')

    def checkpoint(active=None):
        write_json(partial, {'metadata': metadata, 'rows': rows, 'errors': errors,
                             'active_trial': active, 'incomplete': True,
                             'failure_records': failure_records[:MAX_FAILURE_RECORDS],
                             'acceptance_verdict': 'none', 'events_truncated': False})

    def worker():
        for trial in plan:
            trial['go'].wait()  # Setup synchronization is outside trial budget; watchdog covers it.
            if stop.is_set():
                return
            kind, obj, mode = trial['kind'], trial['obj'], trial['mode']
            calls, completed, value, cap_hit, failure = [], False, None, False, None
            begin = time.monotonic_ns()
            cpu_begin = time.thread_time_ns()
            deadline = begin + BUDGET_NS
            trial['entered'].set()  # Controller gate, not proof of entering native wait.
            gate_return = time.monotonic_ns()
            try:
                while True:
                    derived = time.monotonic_ns()
                    remaining = deadline - derived
                    if remaining < 1000:
                        break
                    if len(calls) == MAX_CALLS:
                        cap_hit = True
                        break
                    requested = min(remaining, QUANTUM_NS) if mode == 'quantum' else remaining
                    # Positive timeout on actual API; no nonblocking spin or cosmetic sleep.
                    cpu_enter = time.thread_time_ns()
                    api_enter = time.monotonic_ns()
                    completed, value = one_wait(kind, obj, requested / 1_000_000_000)
                    api_return = time.monotonic_ns()
                    cpu_return = time.thread_time_ns()
                    calls.append({'request_derived_ns': derived, 'requested_ns': requested,
                                  'api_enter_ns': api_enter, 'api_return_ns': api_return,
                                  'cpu_enter_ns': cpu_enter, 'cpu_return_ns': cpu_return,
                                  'completed': bool(completed)})
                    if completed:
                        break
            except BaseException as exc:
                record = bounded_failure(exc, 'worker')
                failure_records.append(record)
                failure = record['error_repr']
            end = time.monotonic_ns()
            cpu_end = time.thread_time_ns()
            trial['result'] = {'kind': kind, 'scenario': trial['scenario'], 'sample': trial['sample'],
                'mode': mode, 'worker_ident': threading.get_ident(), 'native_id': threading.get_native_id(),
                'fixture_metadata': trial['metadata'], 'trial_begin_ns': begin, 'deadline_ns': deadline,
                'entered_gate_return_ns': gate_return, 'trial_return_ns': end,
                'cpu_begin_ns': cpu_begin, 'cpu_return_ns': cpu_end,
                'wall_ms': (end - begin) / 1e6, 'thread_cpu_ms': (cpu_end - cpu_begin) / 1e6,
                'deadline_overrun_ms': (end - deadline) / 1e6,
                'completed': bool(completed), 'value': value, 'cap_hit': cap_hit,
                'error': failure, 'calls': calls}
            # Success Lock ownership is released only after the measured caller return.
            if kind == 'lock' and completed:
                obj.release()
            trial['done'].set()
            if failure:
                return

    thread = threading.Thread(target=worker, name='single-modern-primitive-worker', daemon=True)
    checkpoint()
    thread.start()
    try:
        for trial in plan:
            label = {k: trial[k] for k in ('kind', 'scenario', 'sample', 'mode')}
            checkpoint(label)
            trial['go'].set()
            if not trial['entered'].wait(CONTROLLER_GATE_SECONDS):
                raise RuntimeError('worker entry gate did not complete')
            completion_begin = completion_return = None
            if trial['scenario'] == 'completion':
                completion_begin = time.monotonic_ns()
                complete(trial['kind'], trial['obj'])
                completion_return = time.monotonic_ns()
            if not trial['done'].wait(CONTROLLER_GATE_SECONDS):
                raise RuntimeError('worker did not return in controller envelope')
            row = trial['result']
            row['controller_completion_begin_ns'] = completion_begin
            row['controller_completion_return_ns'] = completion_return
            row['completion_scope'] = 'entered gate precedes API; success release may race first wait entry'
            rows.append(row)
            if trial['scenario'] == 'held':
                complete(trial['kind'], trial['obj'])  # Holder retained fixture through recorded return.
            checkpoint()
            if row['error']:
                raise RuntimeError('recorded worker exception: ' + row['error'])
    except BaseException as exc:
        record = bounded_failure(exc, 'controller')
        failure_records.append(record)
        errors.append(record['error_repr'])
        checkpoint(label if 'label' in locals() else None)
    finally:
        stop.set()
        for trial in plan:
            trial['go'].set()
        thread.join(timeout=CONTROLLER_GATE_SECONDS)

    valid = len(rows) == len(plan) and not errors and not thread.is_alive()
    for row in rows:
        valid = valid and not row['cap_hit'] and not row['error'] and bool(row['calls'])
        valid = valid and row['completed'] == (row['scenario'] == 'completion')
        valid = valid and row['deadline_ns'] - row['trial_begin_ns'] == BUDGET_NS
        for call in row['calls']:
            remaining = row['deadline_ns'] - call['request_derived_ns']
            expected = min(remaining, QUANTUM_NS) if row['mode'] == 'quantum' else remaining
            valid = valid and call['requested_ns'] == expected and expected > 0
            valid = valid and call['request_derived_ns'] <= call['api_enter_ns'] <= call['api_return_ns'] <= row['trial_return_ns']
    valid = valid and len({r['native_id'] for r in rows}) == 1
    payload = {'diagnostic_valid': bool(valid), 'acceptance_verdict': 'none',
               'metadata': metadata, 'rows': rows, 'errors': errors,
               'failure_records': failure_records[:MAX_FAILURE_RECORDS],
               'incomplete': len(rows) != len(plan), 'events_truncated': False}
    write_json(output, payload)
    return 0 if valid else 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=HERE / 'results.json')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.child:
        return run_child(output)
    freeze = json.loads((HERE / 'freeze-before.json').read_text(encoding='utf-8'))
    if freeze['harness_sha256'] != source_hash():
        raise RuntimeError('source freeze invalidated; refusing measurement')
    command = [sys.executable, str(Path(__file__).resolve()), '--child', '--output', str(output)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    expired = False
    try:
        stdout, stderr = process.communicate(timeout=WATCHDOG_SECONDS)
    except subprocess.TimeoutExpired:
        expired = True
        process.kill()
        stdout, stderr = process.communicate()
    control = {'source_sha256': source_hash(), 'command': command, 'watchdog_seconds': WATCHDOG_SECONDS,
               'watchdog_expired': expired, 'child_exit': process.returncode,
               'stdout': stdout[-16000:].decode('utf-8', errors='replace'),
               'stderr': stderr[-16000:].decode('utf-8', errors='replace'),
               'acceptance_verdict': 'none'}
    partial = output.with_name(output.stem + '.partial.json')
    failed = expired or process.returncode or not output.exists()
    if failed:
        # Preserve the child's exact final object before replacing the driver result.
        child_result = output.with_name(output.stem + '.child-result.json')
        if output.exists():
            os.replace(output, child_result)
        child_receipt = failure_artifact_receipt(child_result)
        checkpoint_receipt = failure_artifact_receipt(partial)
        retained = []
        for record in child_receipt['failure_records'] + checkpoint_receipt['failure_records']:
            if record not in retained and len(retained) < MAX_FAILURE_RECORDS:
                retained.append(record)
        control['child_result_receipt'] = child_receipt
        control['checkpoint_receipt'] = checkpoint_receipt
        control['failure_records'] = retained
        write_json(output.with_name(output.stem + '.control.json'), control)
        write_json(output, {'diagnostic_valid': False, 'incomplete': True,
                           'acceptance_verdict': 'none', 'control': control,
                           'child_result_receipt': child_receipt,
                           'preserved_checkpoint': checkpoint_receipt,
                           'failure_records': retained,
                           'errors': [record['error_repr'] for record in retained]})
        return 2
    write_json(output.with_name(output.stem + '.control.json'), control)
    payload = json.loads(output.read_text(encoding='utf-8'))
    print(json.dumps({'diagnostic_valid': payload['diagnostic_valid'],
                      'trials': len(payload['rows']), 'errors': payload['errors'],
                      'acceptance_verdict': 'none', 'source_sha256': source_hash()}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('DIAGNOSTIC ERROR: ' + repr(exc), file=sys.stderr)
        raise SystemExit(2)
