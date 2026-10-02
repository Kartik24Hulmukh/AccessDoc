"""Protected CI-only, read-only Vercel project access verification.

Never outputs arbitrary upstream metadata, URLs, IDs, errors, env values or the
credential. No redirects, account-level reads, configuration writes or deploys.
Linux main-process alarm and remaining-budget checks bound interruptible Python
work; native callbacks can defer signal delivery. The CI runner has a separate
three-minute job limit. No network is attempted without the alarm guard. Scope is not
independently certified by a successful project read.
Candidate readiness is strictly metadata-only: matching documented project,
account and Git source fields cannot certify build contents or authorize promotion.
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


def unique_object(pairs):
    """Duplicate JSON names cannot silently replace a binding or SHA."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError('RESPONSE_INVALID')
        result[key] = value
    return result


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
                obj = json.loads(data, object_pairs_hook=unique_object,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
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


def repository_id(value):
    # GitHub IDs in Vercel link/gitSource may be integers or decimal strings.
    # bool is not an integer identity; no float coercion or opaque guesses.
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,30}', value):
        return value
    raise VerificationError('REPOSITORY_ID_INVALID')


def project_repository(project):
    # Current v9 schema uses link. Retain the historical gitRepository input
    # shape, but never let it override a contradictory documented link.
    links = [project[key] for key in ('link', 'gitRepository') if key in project]
    if not links:
        raise VerificationError('PROJECT_BINDING_FAILED')
    ids = []
    for git in links:
        if (not isinstance(git, dict) or git.get('type') != 'github'
                or git.get('org') != EXPECTED_OWNER or git.get('repo') != EXPECTED_REPO):
            raise VerificationError('PROJECT_BINDING_FAILED')
        if 'repoId' in git:
            ids.append(repository_id(git['repoId']))
    if len(set(ids)) > 1:
        raise VerificationError('PROJECT_BINDING_FAILED')
    return ids[0] if ids else None


def deployment_facts(deployment, project_id, account_id, repo_id):
    """Check EVERY supplied binding; return facts, not authority.

    Documented shapes: v6 list uid/projectId/meta; v13 owner detail
    id/projectId/ownerId/gitSource (+ optional project/team/gitRepo).
    Unknown or reduced views cannot establish exact-candidate identity.
    https://vercel.com/docs/rest-api/deployments/list-deployments
    https://vercel.com/docs/rest-api/deployments/get-a-deployment-by-id-or-url
    """
    if not isinstance(deployment, dict):
        raise VerificationError('DEPLOYMENT_LIST_INVALID')
    ids = [deployment[k] for k in ('id', 'uid') if k in deployment]
    if any(not isinstance(v, str) or not re.fullmatch(r'dpl_[A-Za-z0-9]{10,64}', v)
           for v in ids) or len(set(ids)) > 1:
        raise VerificationError('DEPLOYMENT_ID_INVALID')
    states = [deployment[k] for k in ('readyState', 'state', 'status') if k in deployment]
    allowed = {'READY', 'ERROR', 'BUILDING', 'INITIALIZING', 'QUEUED',
               'CANCELED', 'BLOCKED', 'DELETED'}
    if any(not isinstance(v, str) or v not in allowed for v in states) or len(set(states)) > 1:
        raise VerificationError('DEPLOYMENT_STATE_CONFLICT')
    for field, nested, expected in (('projectId', 'project', project_id),
                                    ('ownerId', 'team', account_id)):
        values = [deployment[field]] if field in deployment else []
        if nested in deployment:
            obj = deployment[nested]
            if not isinstance(obj, dict) or 'id' not in obj:
                raise VerificationError('DEPLOYMENT_BINDING_FAILED')
            values.append(obj['id'])
        if any(not isinstance(v, str) or v != expected for v in values):
            raise VerificationError('DEPLOYMENT_BINDING_FAILED')
    meta = deployment.get('meta', {})
    if not isinstance(meta, dict):
        raise VerificationError('DEPLOYMENT_METADATA_INVALID')
    for field, expected in (('githubCommitOrg', EXPECTED_OWNER),
                            ('githubCommitRepo', EXPECTED_REPO)):
        if field in meta and meta[field] != expected:
            raise VerificationError('DEPLOYMENT_BINDING_FAILED')
    if 'githubRepoId' in meta:
        if repo_id is None or repository_id(meta['githubRepoId']) != repo_id:
            raise VerificationError('DEPLOYMENT_BINDING_FAILED')
    source_repository_bound = False
    for field in ('gitSource', 'gitRepo'):
        if field not in deployment:
            continue
        git = deployment[field]
        # The documented v13 gitRepo is nullable. It is connected-repository
        # decoration, not the required originating gitSource identity.
        if field == 'gitRepo' and git is None:
            continue
        if not isinstance(git, dict) or git.get('type') != 'github':
            raise VerificationError('DEPLOYMENT_BINDING_FAILED')
        named = False
        if 'org' in git or 'repo' in git:
            if git.get('org') != EXPECTED_OWNER or git.get('repo') != EXPECTED_REPO:
                raise VerificationError('DEPLOYMENT_BINDING_FAILED')
            named = True
        identified = False
        if 'repoId' in git:
            if repo_id is None or repository_id(git['repoId']) != repo_id:
                raise VerificationError('DEPLOYMENT_BINDING_FAILED')
            identified = True
        if not (named or identified):
            raise VerificationError('DEPLOYMENT_BINDING_FAILED')
        if field == 'gitSource':
            source_repository_bound = True
    shas = [meta['githubCommitSha']] if 'githubCommitSha' in meta else []
    source = deployment.get('gitSource', {})
    if 'sha' in source:
        shas.append(source['sha'])
    if any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-fA-F]{40}', v)
           for v in shas) or len({v.lower() for v in shas}) > 1:
        raise VerificationError('DEPLOYMENT_SHA_CONFLICT')
    return {
        'id': ids[0] if ids else None,
        'state': states[0] if states else None,
        'sha': shas[0].lower() if shas else None,
        # Require documented direct bindings, not just nested display names.
        'bound': (bool(ids) and deployment.get('projectId') == project_id
                  and account_id is not None
                  and deployment.get('ownerId') == account_id
                  and source_repository_bound and 'sha' in source),
    }


def verify(client, expected_commit):
    if not isinstance(expected_commit, str) or not re.fullmatch(r'[0-9a-f]{40}', expected_commit):
        raise VerificationError('COMMIT_CONFIG_INVALID')
    project = client.get('/v9/projects/' + EXPECTED_PROJECT)
    if not isinstance(project, dict) or project.get('name') != EXPECTED_PROJECT:
        raise VerificationError('PROJECT_BINDING_FAILED')
    repo_id = project_repository(project)
    project_id = project.get('id')
    if not isinstance(project_id, str) or not re.fullmatch(r'prj_[A-Za-z0-9]{10,64}', project_id):
        raise VerificationError('PROJECT_ID_INVALID')
    account_id = project.get('accountId')
    if account_id is not None and (not isinstance(account_id, str)
            or not re.fullmatch(r'[A-Za-z0-9_]{10,80}', account_id)):
        raise VerificationError('PROJECT_ACCOUNT_INVALID')
    # No new account-level reads: use the account returned by the project
    # only to preserve team context, never to assert independent token scope.
    team_query = {'teamId': account_id} if account_id and account_id.startswith('team_') else {}
    listing = client.get('/v6/deployments?' + urllib.parse.urlencode({
        'projectId': project_id, 'limit': 20, **team_query,
    }))
    if not isinstance(listing, dict):
        raise VerificationError('DEPLOYMENT_LIST_INVALID')
    deployments = listing.get('deployments')
    if not isinstance(deployments, list) or len(deployments) > 20:
        raise VerificationError('DEPLOYMENT_LIST_INVALID')
    ready_count = 0
    exact_candidate_ready = False
    for deployment in deployments:
        facts = deployment_facts(deployment, project_id, account_id, repo_id)
        ready_count += facts['state'] == 'READY'
        if facts['sha'] != expected_commit or facts['state'] != 'READY':
            continue
        if not facts['bound']:
            # IDs only, never upstream URL/hostname; at most 20 detail GETs,
            # all inside the original absolute deadline/body/redirect guard.
            if facts['id'] is None or account_id is None:
                continue
            detail = client.get('/v13/deployments/' + facts['id'] + '?' +
                                urllib.parse.urlencode({'withGitRepoInfo': 'true', **team_query}))
            observed = deployment_facts(detail, project_id, account_id, repo_id)
            if (observed['id'] != facts['id'] or observed['state'] != facts['state']
                    or observed['sha'] != facts['sha'] or not observed['bound']):
                raise VerificationError('DEPLOYMENT_DETAIL_BINDING_FAILED')
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
