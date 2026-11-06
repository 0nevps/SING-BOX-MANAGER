import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sbmanager.core.state_manager import StateStore
from sbmanager.modules.manager import Manager
from sbmanager.security import ValidationError


def add_parallel(directory, number):
    Manager(StateStore(directory)).add_user(f'parallel-{number}')


class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / 'state')
        self.manager = Manager(self.store)
        self.user = self.manager.add_user('Alice')
        self.first = self.manager.add_inbound('REALITY', 'reality')
        self.second = self.manager.add_inbound('HY2', 'hysteria2')
        self.manager.grant(self.user, self.first)
        self.manager.grant(self.user, self.second)
        self.egress = self.manager.save_egress('JP', 'socks5', {
            'server': 'proxy.example.com', 'port': 1080,
            'username': 'alice', 'password': 'secret', 'udp': False})

    def test_authorization_isolation_and_reset(self):
        before = self.store.read()['users'][self.user]['grants']
        self.assertNotEqual(before[self.first], before[self.second])
        self.manager.reset_credential(self.user, self.first)
        after = self.store.read()['users'][self.user]['grants']
        self.assertNotEqual(before[self.first], after[self.first])
        self.assertEqual(before[self.second], after[self.second])
        self.manager.revoke(self.user, self.first)
        self.assertEqual({self.second: before[self.second]}, self.store.read()['users'][self.user]['grants'])

    def test_disable_preserves_grants_and_bindings(self):
        self.manager.bind(self.user, self.first, self.egress)
        before = self.store.read()
        self.manager.set_enabled(self.user, False)
        after = self.store.read()
        self.assertFalse(after['users'][self.user]['enabled'])
        self.assertEqual(before['bindings'], after['bindings'])
        self.assertEqual(before['users'][self.user]['grants'], after['users'][self.user]['grants'])

    def test_binding_isolation_and_delete_protection(self):
        self.manager.bind(self.user, self.first, self.egress)
        self.manager.bind(self.user, self.second)
        with self.assertRaises(ValidationError):
            self.manager.delete_egress(self.egress)
        with self.assertRaises(ValidationError):
            self.manager.unbind(self.user, self.first, self.egress)
        self.manager.bind(self.user, self.first)
        self.manager.unbind(self.user, self.first, self.egress)
        self.manager.delete_egress(self.egress)
        self.assertEqual(2, len(self.store.read()['bindings']))

    def test_revoke_cleans_only_its_binding(self):
        self.manager.bind(self.user, self.first, self.egress)
        self.manager.bind(self.user, self.second, self.egress)
        self.manager.revoke(self.user, self.first)
        bindings = self.store.read()['bindings']
        self.assertEqual([f'{self.user}:{self.second}'], list(bindings))
        self.manager.delete_user(self.user)
        self.assertEqual({}, self.store.read()['bindings'])

    def test_duplicate_and_invalid_operations_preserve_bytes(self):
        before = self.store.path.read_bytes()
        for operation in [lambda: self.manager.add_user('Alice'),
                          lambda: self.manager.grant(self.user, self.first),
                          lambda: self.manager.bind('missing', self.first, self.egress)]:
            with self.assertRaises(ValidationError):
                operation()
            self.assertEqual(before, self.store.path.read_bytes())

    def test_replacement_failure_preserves_state(self):
        before = self.store.path.read_bytes()
        with patch('sbmanager.core.state_manager.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.manager.add_user('Bob')
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual([], list(self.store.directory.glob('.state-*')))

    def test_permissions_and_redaction(self):
        self.assertEqual(0o700, self.store.directory.stat().st_mode & 0o777)
        self.assertEqual(0o600, self.store.path.stat().st_mode & 0o777)
        summary = json.dumps(self.manager.summary())
        self.assertNotIn('secret', summary)
        for secret in self.store.read()['users'][self.user]['grants'].values():
            self.assertNotIn(secret, summary)

    def test_concurrent_processes_preserve_updates(self):
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
            list(executor.map(add_parallel, [str(self.store.directory)] * 16, range(16)))
        self.assertEqual(17, len(self.store.read()['users']))

    def test_unknown_schema_rejected_without_overwrite(self):
        self.store.path.write_text('{"schema_version": 99}')
        before = self.store.path.read_bytes()
        with self.assertRaises(ValidationError):
            self.manager.add_user('Bob')
        self.assertEqual(before, self.store.path.read_bytes())

    def test_cli_create_list_exit(self):
        result = subprocess.run([sys.executable, 'main.py', '--state-dir', str(self.store.directory)],
                                input='2\n2\nBob\n1\n0\n0\n', text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('Bob', result.stdout)
        self.assertIn('仅保存设置，不操作服务', result.stdout)
        self.assertNotIn('secret', result.stdout)

    def test_invalid_profile_is_rejected(self):
        for port in (True, 0, 65536, '1080'):
            with self.assertRaises(ValidationError):
                self.manager.save_egress('bad', 'socks5', {'server': 'example.com', 'port': port,
                                                        'username': 'u', 'password': 'p'})


if __name__ == '__main__':
    unittest.main()
