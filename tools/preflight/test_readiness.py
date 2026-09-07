import contextlib
import io
import json
import sys
import subprocess
import unittest
from unittest.mock import patch
import github_readiness as g


class ReadinessTests(unittest.TestCase):
    def repo_data(self, visibility='private'):
        return {'full_name': 'alice/demo', 'private': visibility == 'private',
                'visibility': visibility, 'permissions': {'push': True},
                'archived': False, 'disabled': False,
                'clone_url': 'https://github.com/alice/demo.git'}

    def run_check(self, overrides=None, cli_args=None, **check_kwargs):
        values = {'auth': '', 'user': '{"login":"alice"}',
                  'repo': json.dumps(self.repo_data()),
                  'name': 'Alice', 'email': 'alice@example.com',
                  'refs': 'a' * 40 + '\trefs/heads/main\n'}
        values.update(overrides or {})
        def fake(args, **kwargs):
            self.assertFalse({'GH_TOKEN', 'GITHUB_TOKEN', 'GITHUB_PAT'} & kwargs['env'].keys())
            if args[:3] == ['gh', 'auth', 'status']: key = 'auth'
            elif args[:2] == ['gh', 'api']: key = 'user' if args[-1] == 'user' else 'repo'
            elif args[-1] == 'user.name': key = 'name'
            elif args[-1] == 'user.email': key = 'email'
            else:
                self.assertIn('ls-remote', args)
                self.assertEqual(args[-1], 'https://github.com/alice/demo.git')
                key = 'refs'
            value = values[key]
            return subprocess.CompletedProcess(args, 1 if value is None else 0, value or '', 'SECRET-do-not-print')
        with patch.object(g.subprocess, 'run', side_effect=fake):
            if cli_args is not None:
                stdout = io.StringIO()
                with patch.object(sys, 'argv', ['github_readiness.py', '--owner', 'alice',
                                              '--repo', 'demo', '--expected-login', 'alice',
                                              '--workdir', '/root'] + cli_args), contextlib.redirect_stdout(stdout):
                    status = g.main()
                return dict(json.loads(stdout.getvalue()), cli_exit_status=status)
            return g.check('alice', 'demo', 'alice', '/root', **check_kwargs)

    def test_success(self): self.assertTrue(self.run_check()['ready'])
    def test_empty_repo_access(self):
        result = self.run_check({'refs': ''})
        self.assertTrue(result['ready'])
        self.assertEqual(result['git_transport'], 'verified_empty_repository')
    def test_failures(self):
        for key in ['auth', 'user', 'repo', 'name', 'email', 'refs']:
            with self.subTest(key=key):
                result = self.run_check({key: None})
                self.assertFalse(result['ready'])
                self.assertNotIn('SECRET', json.dumps(result))
    def test_login_mismatch(self): self.assertFalse(self.run_check({'user': '{"login":"other"}'})['ready'])
    def test_repo_mismatch(self): self.assertFalse(self.run_check({'repo': '{"full_name":"other/demo"}'})['ready'])
    def test_private_push_and_clean_url(self):
        base = self.repo_data()
        for change in [{'private': False}, {'permissions': {}}, {'permissions': {'push': 'true'}}, {'archived': True}, {'disabled': True}, {'clone_url': 'https://TOKEN' + '@github.com/alice/demo.git'}]:
            with self.subTest(change=change): self.assertFalse(self.run_check({'repo': json.dumps(base | change)})['ready'])
    def test_bad_json(self): self.assertFalse(self.run_check({'repo': 'bad'})['ready'])
    def test_invalid_identifiers(self):
        with patch.object(g.subprocess, 'run') as run:
            self.assertFalse(g.check('../alice', 'demo', 'alice', '/root')['ready'])
            run.assert_not_called()
    def test_timeout(self):
        with patch.object(g.subprocess, 'run', side_effect=subprocess.TimeoutExpired('secret', 1)):
            self.assertFalse(g.check('alice', 'demo', 'alice', '/root')['ready'])
    def test_missing_binary(self):
        with patch.object(g.subprocess, 'run', side_effect=FileNotFoundError('secret')):
            self.assertFalse(g.check('alice', 'demo', 'alice', '/root')['ready'])

    def test_verified_visibility_and_push(self):
        for visibility in ('private', 'public'):
            with self.subTest(visibility=visibility):
                result = self.run_check({'repo': json.dumps(self.repo_data(visibility))},
                                        expected_visibility=visibility)
                self.assertTrue(result['ready'])
                self.assertEqual(result['verified_visibility'], visibility)
                self.assertIs(result['push_permission'], True)
                self.assertNotIn('private_and_push_permission', result)
                self.assertIs(result['push_performed'], False)
                self.assertEqual(result['deployment_credentials'], 'untested')

    def test_default_rejects_public(self):
        result = self.run_check({'repo': json.dumps(self.repo_data('public'))})
        self.assertFalse(result['ready'])
        self.assertEqual(result['failed_stage'], 'repository')

    def test_visibility_fields_fail_closed(self):
        for visibility in ('private', 'public'):
            base = self.repo_data(visibility)
            changes = [{'visibility': value} for value in
                       ('public' if visibility == 'private' else 'private',
                        'internal', 'PRIVATE', '', None, True, [], {})]
            changes += [{'private': value} for value in
                        (visibility != 'private', None, 'true', 'false', 0, 1, [], {})]
            cases = [base | change for change in changes]
            cases += [{k: v for k, v in base.items() if k != field}
                      for field in ('visibility', 'private')]
            for data in cases:
                with self.subTest(visibility=visibility, data=data):
                    result = self.run_check({'repo': json.dumps(data)}, expected_visibility=visibility)
                    self.assertFalse(result['ready'])
                    self.assertEqual(result['failed_stage'], 'repository')
                    self.assertNotIn('verified_visibility', result)
                    self.assertNotIn('push_permission', result)

    def test_repository_safety_in_both_modes(self):
        for visibility in ('private', 'public'):
            base = self.repo_data(visibility)
            changes = [{'permissions': value} for value in
                       ({}, None, [], {'push': False}, {'push': 'true'}, {'push': 1})]
            changes += [{field: value} for field in ('archived', 'disabled')
                        for value in (True, None, 'false', 0)]
            changes += [{'full_name': 'Alice/demo'}, {'full_name': 'alice/other'},
                        {'clone_url': 'https://TOKEN' + '@github.com/alice/demo.git'},
                        {'clone_url': 'https://github.com/alice/other.git'}]
            cases = [base | change for change in changes]
            cases += [{k: v for k, v in base.items() if k != field}
                      for field in ('permissions', 'archived', 'disabled', 'full_name', 'clone_url')]
            for data in cases:
                with self.subTest(visibility=visibility, data=data):
                    result = self.run_check({'repo': json.dumps(data)}, expected_visibility=visibility)
                    self.assertFalse(result['ready'])
                    self.assertEqual(result['failed_stage'], 'repository')
                    self.assertNotIn('TOKEN', json.dumps(result))

    def test_public_auth_identity_transport_and_sanitization(self):
        base = {'repo': json.dumps(self.repo_data('public'))}
        cases = [(key, None) for key in ('auth', 'user', 'repo', 'name', 'email', 'refs')]
        cases += [('user', '{"login":"Alice"}'), ('user', 'SECRET'),
                  ('repo', 'SECRET'), ('repo', 'null'), ('repo', '[]'),
                  ('name', ''), ('email', ''), ('name', 'Alice\nSECRET'),
                  ('email', 'alice\x01SECRET'), ('refs', 'SECRET')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                result = self.run_check(base | {key: value}, expected_visibility='public')
                self.assertFalse(result['ready'])
                self.assertNotIn('SECRET', json.dumps(result))
        self.assertTrue(self.run_check(base | {'refs': ''}, expected_visibility='public')['ready'])
        for error in (FileNotFoundError('SECRET'), subprocess.TimeoutExpired('SECRET', 1)):
            with self.subTest(error=type(error).__name__), patch.object(g.subprocess, 'run', side_effect=error):
                result = g.check('alice', 'demo', 'alice', '/root', expected_visibility='public')
                self.assertFalse(result['ready'])
                self.assertNotIn('SECRET', json.dumps(result))

    def test_invalid_visibility_argument_never_runs_subprocess(self):
        for value in ('internal', 'PUBLIC', '', None, True, [], {}):
            with self.subTest(value=value), patch.object(g.subprocess, 'run') as run:
                result = g.check('alice', 'demo', 'alice', '/root', expected_visibility=value)
                self.assertFalse(result['ready'])
                self.assertEqual(result['failed_stage'], 'arguments')
                run.assert_not_called()

    def test_cli_visibility_and_exit_status(self):
        for args, visibility, status in [([], 'private', 0), ([], 'public', 1),
                (['--expected-visibility', 'private'], 'private', 0),
                (['--expected-visibility', 'private'], 'public', 1),
                (['--expected-visibility', 'public'], 'public', 0),
                (['--expected-visibility', 'public'], 'private', 1)]:
            with self.subTest(args=args, visibility=visibility):
                result = self.run_check({'repo': json.dumps(self.repo_data(visibility))}, cli_args=args)
                self.assertEqual(result['cli_exit_status'], status)
                self.assertEqual(result['ready'], status == 0)
                if status == 0:
                    self.assertEqual(result['verified_visibility'], visibility)
                    self.assertIs(result['push_permission'], True)
        result = self.run_check({'auth': None}, cli_args=['--expected-visibility', 'public'])
        self.assertEqual(result['cli_exit_status'], 1)
        self.assertEqual(result['failed_stage'], 'stored_auth')

    def test_cli_invalid_visibility_never_runs_subprocess(self):
        for args in (['--expected-visibility', 'internal'], ['--expected-visibility']):
            with self.subTest(args=args), patch.object(g.subprocess, 'run') as run, \
                    patch.object(sys, 'argv', ['github_readiness.py', '--owner', 'alice',
                                              '--repo', 'demo', '--expected-login', 'alice'] + args), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    g.main()
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()


if __name__ == '__main__': unittest.main()
