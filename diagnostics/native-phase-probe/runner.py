#!/usr/bin/env python3
"""Fixed native legacy-lock diagnostic, not an acceptance test or runtime patch."""
import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shlex
import subprocess
import sys
import sysconfig
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUDGET_NS = 30_000_000
QUANTUM_NS = 1_000_000
WATCHDOG_SECONDS = 3
MAX_ARTIFACT_BYTES = 256_000


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    text = json.dumps(obj, indent=2, allow_nan=False) + '\n'
    if len(text.encode('utf-8')) > MAX_ARTIFACT_BYTES:
        raise RuntimeError('artifact cap exceeded; no silent truncation')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def build():
    if sys.platform not in ('darwin', 'linux'):
        raise RuntimeError('only Darwin and Linux supported')
    directory = HERE / 'build'
    directory.mkdir(exist_ok=True)
    extension = directory / ('_native_phase_probe' + sysconfig.get_config_var('EXT_SUFFIX'))
    command = shlex.split(sysconfig.get_config_var('LDSHARED') or 'cc -shared')
    command += shlex.split(sysconfig.get_config_var('CFLAGS') or '')
    command += shlex.split(sysconfig.get_config_var('CCSHARED') or '')
    command += ['-std=c11', '-O2', '-Wall', '-Wextra']
    for include in dict.fromkeys([sysconfig.get_path('include'), sysconfig.get_path('platinclude')]):
        if include:
            command += ['-I', include]
    if sys.platform == 'linux':
        command += ['-pthread']
    command += [str(HERE / 'probe.c'), '-o', str(extension)]
    run = subprocess.run(command, capture_output=True, text=True, timeout=30)
    log = (run.stdout + run.stderr)[-32_000:]
    (directory / 'compile.log').write_text(log, encoding='utf-8')
    manifest = {'command': command, 'returncode': run.returncode,
                'source_sha256': digest(HERE / 'probe.c'), 'runner_sha256': digest(HERE / 'runner.py'),
                'configured_cc': sysconfig.get_config_var('CC'),
                'python': sys.version, 'platform': platform.platform(),
                'flags_scope': 'extension compilation only; no inferred CPython wait backend flags'}
    if run.returncode:
        write_json(directory / 'build.json', manifest)
        raise RuntimeError('compile failed; see build/compile.log')
    manifest['extension_sha256'] = digest(extension)
    write_json(directory / 'build.json', manifest)
    return extension, manifest


def worker(output, extension):
    spec = importlib.util.spec_from_file_location('_native_phase_probe', extension)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    metadata = probe.metadata()
    clocks = {k: vars(time.get_clock_info(k)) for k in ('monotonic', 'perf_counter', 'thread_time')}
    if clocks['monotonic']['implementation'] != metadata['native_monotonic_clock']:
        raise RuntimeError('clock-domain implementation mismatch; no uncalibrated subtraction')
    # Main thread establishes ownership/held state before one serial worker begins.
    held = [probe.create_held() for _ in range(6)]
    rows, errors = [], []

    def run():
        try:
            for sample in range(3):
                for mode in ('full', 'quantum'):
                    index = sample * 2 + (mode == 'quantum')
                    before = time.monotonic_ns()
                    row = probe.trial(held[index], mode)
                    after = time.monotonic_ns()
                    row.update(sample=sample, python_before_ns=before, python_after_ns=after)
                    row['phases_ms'] = {
                        'python_to_native_entry': (row['native_entry_ns'] - before) / 1e6,
                        'gil_detach_and_schedule': (row['released_entry_ns'] - row['native_entry_ns']) / 1e6,
                        'detached_native_phase': (row['native_return_ns'] - row['released_entry_ns']) / 1e6,
                        'native_return_instrumentation': (row['before_gil_reattach_ns'] - row['native_return_ns']) / 1e6,
                        'reattach_and_schedule': (row['after_gil_ns'] - row['before_gil_reattach_ns']) / 1e6,
                        'result_build_and_python_resume': (after - row['after_gil_ns']) / 1e6,
                        'total_from_native_entry': (after - row['native_entry_ns']) / 1e6,
                        'native_deadline_overrun': (row['native_return_ns'] - row['deadline_ns']) / 1e6,
                    }
                    rows.append(row)
        except BaseException as exc:
            errors.append(repr(exc))

    thread = threading.Thread(target=run, name='single-native-phase-worker')
    thread.start()
    thread.join()  # External supervising process enforces wall watchdog, no retry.
    invalid = errors or len(rows) != 6
    for row in rows:
        stamps = [row[k] for k in ('python_before_ns', 'native_entry_ns', 'released_entry_ns',
                                  'native_return_ns', 'before_gil_reattach_ns', 'after_gil_ns', 'python_after_ns')]
        invalid = invalid or stamps != sorted(stamps) or row['deadline_ns'] - row['native_entry_ns'] != BUDGET_NS
        invalid = invalid or row['cap_hit'] or row['unexpected_acquisition'] or row['interrupted']
        invalid = invalid or not row['waits'] or len(row['waits']) > 32
        for w in row['waits']:
            # Argument was derived just before W_enter; keep actual timestamps/rounding visible.
            remaining = row['deadline_ns'] - w['request_derived_ns']
            expected_us = min(QUANTUM_NS, remaining) // 1_000 if row['mode'] == 'quantum' else remaining // 1_000
            invalid = invalid or w['requested_us'] != expected_us
            invalid = invalid or w['request_derived_ns'] > w['wait_enter_ns']
            invalid = invalid or w['requested_us'] <= 0 or w['requested_us'] > 30_000
            invalid = invalid or w['status'] != metadata['py_lock_failure']
            invalid = invalid or w['wait_return_ns'] < w['wait_enter_ns']
            if row['mode'] == 'quantum':
                invalid = invalid or w['requested_us'] > 1_000
    info = sys.thread_info
    result = {'diagnostic_valid': not bool(invalid), 'acceptance_verdict': 'none',
              'scope': 'actual public legacy PyThread timed-lock call, not plain Lock/PyMutex or application acceptance',
              'budget_ns': BUDGET_NS, 'quantum_ns': QUANTUM_NS,
              'trials_per_mode': 3, 'one_worker_serial': True, 'watchdog_seconds': WATCHDOG_SECONDS,
              'rows': rows, 'errors': errors, 'events_truncated': False,
              'metadata': metadata, 'clocks': clocks, 'python': sys.version,
              'implementation': platform.python_implementation(), 'platform': platform.platform(),
              'sys_thread_info': {'name': info.name, 'lock': info.lock, 'version': info.version},
              'switch_interval_observed_not_changed': sys.getswitchinterval(),
              'source_sha256': digest(HERE / 'probe.c'), 'runner_sha256': digest(HERE / 'runner.py'),
              'extension_sha256': digest(extension)}
    write_json(output, result)
    # Trial latency itself does NOT change diagnostic exit status or acceptance.
    return 2 if invalid else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=HERE / 'results.json')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--extension', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.worker:
        return worker(output, args.extension.resolve())
    extension, manifest = build()
    command = [sys.executable, str(HERE / 'runner.py'), '--worker', '--extension', str(extension), '--output', str(output)]
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timed_out = False
    try:
        stdout, stderr = child.communicate(timeout=WATCHDOG_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        child.kill()
        stdout, stderr = child.communicate()
    control = {'command': command, 'watchdog_seconds': WATCHDOG_SECONDS, 'watchdog_expired': timed_out,
               'child_exit': child.returncode, 'build': manifest,
               'stderr': stderr[-16_000:].decode('utf-8', errors='replace'),
               'stdout': stdout[-16_000:].decode('utf-8', errors='replace'), 'acceptance_verdict': 'none'}
    write_json(output.with_name(output.stem + '.control.json'), control)
    if timed_out or child.returncode or not output.exists():
        write_json(output, {'diagnostic_valid': False, 'incomplete': True,
                           'reason': 'watchdog expiry or child failure', 'control': control,
                           'acceptance_verdict': 'none'})
        return 2
    data = json.loads(output.read_text(encoding='utf-8'))
    print(json.dumps({'diagnostic_valid': data['diagnostic_valid'], 'acceptance_verdict': 'none',
                      'platform': data['platform'], 'rows': [{'mode': r['mode'], 'sample': r['sample'],
                      'wait_calls': len(r['waits']), 'phases_ms': r['phases_ms']} for r in data['rows']]}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('DIAGNOSTIC ERROR: ' + repr(exc), file=sys.stderr)
        raise SystemExit(2)
