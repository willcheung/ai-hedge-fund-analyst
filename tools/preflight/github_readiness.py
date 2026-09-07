#!/usr/bin/env python3
"""Read-only GitHub source-control gate; never a deployment authorization."""
import argparse
import json
import os
import re
import subprocess


class GateError(Exception):
    pass


def run(args, cwd):
    env = dict(os.environ)
    for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GITHUB_PAT', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN', 'GH_DEBUG', 'GIT_TRACE', 'GIT_TRACE_CURL', 'GIT_CURL_VERBOSE'):
        env.pop(key, None)
    env.update(GH_PROMPT_DISABLED='1', GIT_TERMINAL_PROMPT='0', GH_HOST='github.com')
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        raise GateError('command_unavailable_or_timeout') from None
    if result.returncode:
        raise GateError('command_failed')
    return result.stdout.strip()


def check(owner, repo, expected_login, cwd, expected_visibility='private'):
    out = {'ready': False, 'scope': 'Git source-control start gate only',
           'deployment_credentials': 'untested', 'push_performed': False}
    stage = 'arguments'
    try:
        if expected_visibility not in ('private', 'public'):
            raise GateError('invalid_expected_visibility')
        if not all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', s) for s in (owner, expected_login)) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}', repo):
            raise GateError('invalid_identifier')
        out['target'] = f'{owner}/{repo}'
        stage = 'stored_auth'
        run(['gh', 'auth', 'status', '--hostname', 'github.com'], cwd)
        stage = 'verified_login'
        user = json.loads(run(['gh', 'api', '--hostname', 'github.com', 'user'], cwd))
        if user.get('login') != expected_login:
            raise GateError('login_mismatch')
        out['verified_login'] = expected_login
        stage = 'repository'
        data = json.loads(run(['gh', 'api', '--hostname', 'github.com', f'repos/{owner}/{repo}'], cwd))
        url = f'https://github.com/{owner}/{repo}.git'
        if data.get('full_name') != f'{owner}/{repo}':
            raise GateError('repository_mismatch')
        if data.get('visibility') != expected_visibility or data.get('private') is not (expected_visibility == 'private'):
            raise GateError('repository_visibility_mismatch_or_unknown')
        if data.get('permissions', {}).get('push') is not True:
            raise GateError('push_permission_required')
        if data.get('archived') is not False or data.get('disabled') is not False:
            raise GateError('repository_not_writable_or_state_unknown')
        if data.get('clone_url') != url:
            raise GateError('unexpected_or_credential_bearing_remote_url')
        out['remote_url'] = url
        out['verified_visibility'] = expected_visibility
        out['push_permission'] = True
        stage = 'git_identity'
        for key in ('user.name', 'user.email'):
            value = run(['git', 'config', '--get', key], cwd)
            if not value or any(ord(c) < 32 for c in value):
                raise GateError('missing_or_invalid_git_identity')
        out['git_identity'] = 'configured_in_requested_workdir'
        stage = 'git_transport'
        # Reset credential helpers for this command only; use freshly stored gh auth.
        refs = run(['git', '-c', 'credential.helper=', '-c',
                    'credential.https://github.com.helper=!gh auth git-credential',
                    'ls-remote', url], cwd)
        if refs and not all(re.fullmatch(r'[0-9a-f]{40,64}\s+\S+', line) for line in refs.splitlines()):
            raise GateError('unexpected_git_refs_output')
        out['git_transport'] = 'verified_refs' if refs else 'verified_empty_repository'
        out['ready'] = True
    except (GateError, ValueError, TypeError, AttributeError):
        # Deliberately suppress provider output, stderr, tokens and exception text.
        out['failed_stage'] = stage
        out['error'] = 'Required check failed; inspect this stage securely, not raw logs.'
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--owner', required=True)
    p.add_argument('--repo', required=True)
    p.add_argument('--expected-login', required=True)
    p.add_argument('--expected-visibility', choices=('private', 'public'), default='private',
                   help='Required repository visibility (default: private)')
    p.add_argument('--workdir', default='/root', help='Directory whose effective Git identity is checked')
    a = p.parse_args()
    result = check(a.owner, a.repo, a.expected_login, a.workdir, expected_visibility=a.expected_visibility)
    print(json.dumps(result, indent=2))
    return 0 if result['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
