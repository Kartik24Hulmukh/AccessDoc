"""One marked macOS observation; never a runtime policy or acceptance verdict.

Fresh secret-free child environment, owned process group, CPU/file/wall caps,
source guards and bounded log evidence. Does not upload a new Actions artifact.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

EXPECTED = {
    'diagnostics/native-modern-probe/harness.py': 'c4f33ae49b240390ffe7eb2528a9e090331be67574f5e67c9004224a7f557ad0',
    'diagnostics/native-modern-probe/freeze-before.json': '5c8a196aa77dc06097fbda5c5c5353fb5249c5cbfb598a9aaadb6c9347f2fcb2',
    'diagnostics/native-positive-phase.py': '57f741c2af9de59e52d8a19738964bc105f9c08a0aa274dafa96ed76ec8e3596',
    'app/gateway_transport.py': 'e45c6c2a7ad15e94d402c4e82e32d35d5b8fc0292739861ba5b6cd5e7c40c126',
    'app/otlp_export.py': 'bb239429b02622faa5aa8b4d0ebf8bc4aecfe9982cd0707a94f9cb3d72b90da2',
    'tests/test_otlp_cleanup_ownership.py': 'f5bbebd291ecfc962cf17973a7dc468c85cc4a2dd1147edc32af94fdf710894b',
    'tests/test_native_deadline_races.py': '9c17afc5131fe26c15fe761d8e0903ff9af6b666135ee1e6dda424a5ee6e0fab',
    'tests/test_otlp_deadlines.py': '228fc572b4b977abbbf94d60018fe7ef6e9d36ae4ecc85a19225f8c115038e9a',
}
WALL_SECONDS = 25
CPU_SOFT_SECONDS = 10
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_FILES = 24
MAX_LOG_BYTES = 128 * 1024
MAX_ENTRIES = 128
MAX_DEPTH = 4
MAX_MANIFEST_BYTES = 64 * 1024


def verify_sources(repo):
    observed = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in EXPECTED}
    if observed != EXPECTED:
        raise ValueError('diagnostic source guard mismatch; no experiment admitted')
    return observed


def clean_environment(repo, home):
    env = {name: os.environ[name] for name in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR') if name in os.environ}
    env.update(HOME=str(home), PYTHONPATH=str(repo), PYTHONNOUSERSITE='1',
               PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    return env


def child_limits():
    # Imported only in the POSIX child. Module import remains portable.
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SOFT_SECONDS, CPU_SOFT_SECONDS + 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))


def kill_owned_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def settle_owned_group(process):
    """Terminate descendants even after leader exit; no next run if unsettled."""
    kill_owned_group(process.pid)
    deadline = time.monotonic() + 2
    try:
        process.wait(timeout=max(0, deadline - time.monotonic()))
    except (subprocess.TimeoutExpired, OSError):
        return False
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return True
        # Supervisory group-exit polling, never application deadline policy.
        time.sleep(min(.01, max(0, deadline - time.monotonic())))
    return False


def verify_staged(expected):
    observed = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in expected}
    if any(observed[str(path)] != digest for path, digest in expected.items()):
        raise ValueError('staged diagnostic source mismatch; no experiment admitted')
    return observed


def run_one(label, command, env, directory):
    directory.mkdir(parents=True, exist_ok=False)
    control = {'experiment': label, 'acceptance_verdict': 'none',
               'wall_watchdog_seconds': WALL_SECONDS,
               'cpu_soft_seconds_per_process': CPU_SOFT_SECONDS,
               'file_bytes_cap_per_child_file': MAX_FILE_BYTES,
               'environment_names': sorted(env), 'child_exit': None,
               'watchdog_expired': False}
    started = time.monotonic()
    process = None
    control['group_settled'] = False
    try:
        with (directory / 'stdout.log').open('wb') as out, (directory / 'stderr.log').open('wb') as err:
            process = subprocess.Popen(command, stdout=out, stderr=err, env=env,
                                       start_new_session=True, preexec_fn=child_limits)
            try:
                process.wait(timeout=max(0, WALL_SECONDS - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                control['watchdog_expired'] = True
    except Exception as exc:
        control['launch_error_type'] = type(exc).__name__
    finally:
        if process is not None:
            try:
                control['group_settled'] = settle_owned_group(process)
            except Exception as exc:
                control['cleanup_error_type'] = type(exc).__name__
            control['child_exit'] = process.returncode
        else:
            control['group_settled'] = True  # No process was created.
    control['elapsed_seconds'] = time.monotonic() - started
    control['failed'] = (control['watchdog_expired'] or not control['group_settled'] or
                         'launch_error_type' in control or control['child_exit'] != 0)
    for name in ('stdout.log', 'stderr.log'):
        path = directory / name
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            control['failed'] = True
            control.setdefault('oversized_log_files', []).append(name)
    (directory / 'wrapper-control.json').write_text(json.dumps(control, indent=2), encoding='utf-8')
    return control


def evidence_bytes(results):
    """Finite fd-relative traversal; no symlink following or unbounded reads."""
    if os.name != 'posix':
        raise ValueError('fd-relative evidence collection requires POSIX; fail closed')
    buffer = io.BytesIO()
    manifest = {'acceptance_verdict': 'none', 'files': [], 'omitted': [],
                'entries_seen': 0, 'traversal_truncated': False}
    total = 0
    flags = os.O_RDONLY | os.O_NOFOLLOW
    def omit(name, reason):
        manifest['omitted'].append({'name': name[:256], 'reason': reason})
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
        def walk(directory_fd, prefix, depth):
            nonlocal total
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    if manifest['entries_seen'] >= MAX_ENTRIES:
                        manifest['traversal_truncated'] = True
                        return
                    manifest['entries_seen'] += 1
                    name = prefix + entry.name
                    if len(name) > 256:
                        omit(name, 'name-cap'); continue
                    fd = None
                    try:
                        fd = os.open(entry.name, flags | os.O_NONBLOCK, dir_fd=directory_fd)
                        metadata = os.fstat(fd)
                        if stat.S_ISDIR(metadata.st_mode):
                            if depth >= MAX_DEPTH:
                                omit(name, 'depth-cap')
                            else:
                                walk(fd, name + '/', depth + 1)
                            continue
                        if not stat.S_ISREG(metadata.st_mode):
                            omit(name, 'not-regular'); continue
                        cap = MAX_LOG_BYTES if name.endswith('.log') else MAX_FILE_BYTES
                        cap = min(cap, MAX_TOTAL_BYTES - MAX_MANIFEST_BYTES - total)
                        if metadata.st_size > cap or len(manifest['files']) >= MAX_FILES:
                            omit(name, 'explicit-evidence-cap'); continue
                        chunks = []; remaining = cap + 1
                        while remaining:
                            chunk = os.read(fd, min(65536, remaining))
                            if not chunk: break
                            chunks.append(chunk); remaining -= len(chunk)
                        data = b''.join(chunks)
                        after = os.fstat(fd)
                        if len(data) > cap or len(data) != metadata.st_size or (metadata.st_size, metadata.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            omit(name, 'changed-or-oversized'); continue
                        total += len(data)
                        archive.writestr(name, data)
                        manifest['files'].append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
                    except OSError:
                        omit(name, 'unsafe-or-unreadable')
                    finally:
                        if fd is not None: os.close(fd)
        root_fd = os.open(results, flags | os.O_DIRECTORY)
        try: walk(root_fd, '', 0)
        finally: os.close(root_fd)
        encoded = json.dumps(manifest, separators=(',', ':')).encode()
        if len(encoded) > MAX_MANIFEST_BYTES:
            raise ValueError('evidence manifest cap exceeded')
        archive.writestr('bounded-evidence-manifest.json', encoded)
    data = buffer.getvalue()
    if len(data) > MAX_TOTAL_BYTES:
        raise ValueError('complete evidence ZIP cap exceeded')
    return data, manifest


def emit_evidence(results):
    data, manifest = evidence_bytes(results)
    print('ACCESSDOC_DIAG_BEGIN ' + json.dumps({'sha256': hashlib.sha256(data).hexdigest(),
          'zip_bytes': len(data), 'acceptance_verdict': 'none', 'omitted_files': len(manifest['omitted'])}))
    encoded = base64.b64encode(data).decode('ascii')
    for offset in range(0, len(encoded), 4096):
        print('ACCESSDOC_DIAG_DATA ' + encoded[offset:offset + 4096])
    print('ACCESSDOC_DIAG_END')
    return not manifest['omitted'] and not manifest['traversal_truncated']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    repo = args.repo.resolve()
    runner_before = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    before = verify_sources(repo)
    if args.validate_only:
        print(json.dumps({'source_guard': 'PASS', 'experiments_executed': 0,
                          'acceptance_verdict': 'none', 'source_hashes': before}))
        return 0
    if sys.platform != 'darwin':
        raise ValueError('measurement launch is macOS-only; no experiment admitted')
    with tempfile.TemporaryDirectory(prefix='accessdoc-one-modern-', dir=os.environ.get('RUNNER_TEMP')) as raw:
        root = Path(raw)
        if root.is_relative_to(repo):
            raise ValueError('diagnostic output/input root must be outside the repository')
        inputs, results, home = root / 'inputs', root / 'results', root / 'home'
        inputs.mkdir(); results.mkdir(); home.mkdir()
        modern = inputs / 'modern'; modern.mkdir()
        for name in ('harness.py', 'freeze-before.json'):
            (modern / name).write_bytes((repo / 'diagnostics/native-modern-probe' / name).read_bytes())
        positive = inputs / 'positive.py'
        positive.write_bytes((repo / 'diagnostics/native-positive-phase.py').read_bytes())
        env = clean_environment(repo, home)
        staged_expected = {modern / 'harness.py': EXPECTED['diagnostics/native-modern-probe/harness.py'],
                           modern / 'freeze-before.json': EXPECTED['diagnostics/native-modern-probe/freeze-before.json'],
                           positive: EXPECTED['diagnostics/native-positive-phase.py']}
        staged = None
        controls = []
        guard_failed = False
        try:
            staged = verify_staged(staged_expected)
            controls.append(run_one('modern', [sys.executable, str(modern / 'harness.py'),
                '--output', str(results / 'modern' / 'results.json')], env, results / 'modern'))
            if controls[-1]['group_settled']:
                verify_staged(staged_expected)
                controls.append(run_one('positive', [sys.executable, str(positive), '--repo', str(repo),
                    '--output', str(results / 'positive' / 'results.json')], env, results / 'positive'))
        finally:
            try:
                after = verify_sources(repo)
                guard_error = None
                if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != runner_before:
                    raise ValueError('launcher changed')
            except Exception as exc:
                after = None
                guard_error = type(exc).__name__
                guard_failed = True
            (results / 'launch-identity.json').write_text(json.dumps({'before': before, 'after': after,
                'source_guard_error_type': guard_error,
                'unchanged': before == after, 'experiments': controls,
                'runner_sha256_before': runner_before, 'staged_sha256': staged,
                'runner_sha256_after': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'acceptance_verdict': 'none'}, indent=2), encoding='utf-8')
            complete = emit_evidence(results)
        return 2 if guard_failed or not complete or len(controls) != 2 or any(c['failed'] for c in controls) else 0


if __name__ == '__main__':
    raise SystemExit(main())
