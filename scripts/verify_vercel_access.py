"""Protected CI-only, read-only Vercel project access verification.

Never outputs arbitrary upstream metadata, URLs, IDs, errors, env values or the
credential. No redirects, account-level reads, configuration writes or deploys.
Linux main-process alarm and remaining-budget checks bound interruptible Python
work; native callbacks can defer signal delivery. The CI runner has a separate
three-minute job limit. No network is attempted without the alarm guard. Scope is not
independently certified by a successful project read.
"""
import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import re
import signal
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_ORIGIN = 'https://api.vercel.com'
EXPECTED_PROJECT = 'access-doc'
EXPECTED_OWNER = 'Kartik24Hulmukh'
EXPECTED_REPO = 'AccessDoc'
MAX_RESPONSE_BYTES = 1_048_576


class VerificationError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@contextlib.contextmanager
def deadline_guard(seconds):
    if not (hasattr(signal, 'SIGALRM') and hasattr(signal, 'setitimer')
            and threading.current_thread() is threading.main_thread()):
        raise VerificationError('TIMEOUT_GUARD_UNAVAILABLE')
    if not math.isfinite(seconds) or not 0 < seconds <= 90:
        raise VerificationError('TIMEOUT_CONFIG_INVALID')
    if signal.getitimer(signal.ITIMER_REAL)[0]:
        raise VerificationError('TIMEOUT_GUARD_CONFLICT')
    previous = signal.getsignal(signal.SIGALRM)
    def expired(*_):
        raise VerificationError('DEADLINE_EXCEEDED')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class VercelClient:
    def __init__(self, token, deadline, opener=None):
        self.token = token
        self.deadline = deadline
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def get(self, path):
        if not path.startswith('/') or path.startswith('//') or '\\' in path:
            raise VerificationError('REQUEST_BOUNDARY_FAILED')
        url = API_ORIGIN + path
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise VerificationError('DEADLINE_EXCEEDED')
        req = urllib.request.Request(url, method='GET', headers={
            'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/json', 'User-Agent': 'AccessDoc-readonly-verification',
        })
        try:
            with self.opener.open(req, timeout=min(10, remaining)) as response:
                if response.status != 200 or response.geturl() != url:
                    raise VerificationError('RESPONSE_BOUNDARY_FAILED')
                if response.headers.get_content_type() != 'application/json':
                    raise VerificationError('RESPONSE_INVALID')
                data = bytearray()
                while True:
                    if time.monotonic() >= self.deadline:
                        raise VerificationError('DEADLINE_EXCEEDED')
                    chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise VerificationError('RESPONSE_TOO_LARGE')
                obj = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if not isinstance(obj, dict):
                    raise VerificationError('RESPONSE_INVALID')
                return obj
        except urllib.error.HTTPError as error:
            # Never read or print provider error bodies/headers (may reflect token).
            status = error.code
            error.close()
            code = ('TOKEN_REJECTED' if status in (401, 403) else
                    'PROJECT_NOT_FOUND' if status == 404 else
                    'REDIRECT_REJECTED' if 300 <= status < 400 else 'UPSTREAM_HTTP_FAILED')
            raise VerificationError(code) from None
        except VerificationError:
            raise
        except Exception:
            raise VerificationError('REQUEST_FAILED') from None


def verify(client, expected_commit):
    project = client.get('/v9/projects/' + EXPECTED_PROJECT)
    git = project.get('gitRepository')
    if (project.get('name') != EXPECTED_PROJECT or not isinstance(git, dict)
            or git.get('type') != 'github' or git.get('org') != EXPECTED_OWNER
            or git.get('repo') != EXPECTED_REPO):
        raise VerificationError('PROJECT_BINDING_FAILED')
    project_id = project.get('id')
    if not isinstance(project_id, str) or not re.fullmatch(r'prj_[A-Za-z0-9]{10,64}', project_id):
        raise VerificationError('PROJECT_ID_INVALID')
    listing = client.get('/v6/deployments?' + urllib.parse.urlencode({
        'projectId': project_id, 'limit': 20,
    }))
    deployments = listing.get('deployments')
    if not isinstance(deployments, list) or len(deployments) > 20:
        raise VerificationError('DEPLOYMENT_LIST_INVALID')
    ready_count = 0
    exact_candidate_ready = False
    for deployment in deployments:
        if not isinstance(deployment, dict):
            raise VerificationError('DEPLOYMENT_LIST_INVALID')
        state = deployment.get('readyState', deployment.get('state'))
        ready_count += state == 'READY'
        meta, source = deployment.get('meta', {}), deployment.get('gitSource', {})
        meta = meta if isinstance(meta, dict) else {}
        source = source if isinstance(source, dict) else {}
        sha = source.get('sha', meta.get('githubCommitSha'))
        if sha == expected_commit and state == 'READY':
            exact_candidate_ready = True
    return {
        'pass': True, 'mode': 'read-only', 'project_binding_verified': True,
        'token_scope_independently_verified': False,
        'expected_project': EXPECTED_PROJECT, 'expected_repository': EXPECTED_OWNER + '/' + EXPECTED_REPO,
        'verifier_source_commit': expected_commit,
        'deployment_count': len(deployments), 'ready_deployment_count': ready_count,
        'exact_candidate_ready_metadata': exact_candidate_ready,
        'functional_smoke_verified': False, 'production_configuration_verified': False,
        'production_changes_performed': False,
    }


def report_without_credential(report, token):
    encoded = json.dumps(report, sort_keys=True)
    if token and (token.casefold() in encoded.casefold() or
                  urllib.parse.quote(token, safe='').casefold() in encoded.casefold()):
        # No reflected ID/commit/error or redaction placeholder leaks the value.
        return {}, False
    return report, bool(report.get('pass'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='vercel-access.json')
    args = parser.parse_args(argv)
    token = os.getenv('VERCEL_TOKEN', '')
    commit = os.getenv('TARGET_COMMIT', '')
    try:
        if not token:
            raise VerificationError('TOKEN_MISSING')
        if len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise VerificationError('TOKEN_INVALID_FORMAT')
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise VerificationError('COMMIT_CONFIG_INVALID')
        with deadline_guard(45):
            report = verify(VercelClient(token, time.monotonic() + 45), commit)
    except VerificationError as error:
        report = {'pass': False, 'mode': 'read-only', 'error_code': error.code,
                  'production_changes_performed': False}
    except Exception:
        report = {'pass': False, 'mode': 'read-only', 'error_code': 'VERIFICATION_FAILED',
                  'production_changes_performed': False}
    report, ok = report_without_credential(report, token)
    encoded = json.dumps(report, indent=2) + '\n'
    Path(args.output).write_text(encoded, encoding='utf-8')
    print(encoded, end='')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
