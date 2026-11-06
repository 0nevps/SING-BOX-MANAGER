import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sbmanager.cli import run
from sbmanager.core.config_builder import build
from sbmanager.core.state_manager import StateStore
from sbmanager.core.transaction_manager import Deployment
from sbmanager.modules.manager import Manager
from sbmanager.security import ValidationError
from sbmanager.system.singbox import SingBox
from test_deployment import Engine, Service


class ForwardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / 'state')
        self.manager = Manager(self.store)
        self.values = {'name': 'DNS', 'listen': '127.0.0.1', 'listen_port': 15353,
                       'target': '1.1.1.1', 'target_port': 53, 'network': 'both'}

    def test_forward_only_and_protocols(self):
        for index, network in enumerate(('both', 'tcp', 'udp')):
            key = self.manager.add_forward({**self.values, 'network': network, 'listen_port': 15353 + index})
            config = build(self.store.read())
            node = config['inbounds'][-1]
            self.assertEqual('direct', node['type'])
            self.assertEqual('forward-' + key, node['tag'])
            self.assertEqual('1.1.1.1', node['override_address'])
            self.assertEqual(53, node['override_port'])
            self.assertNotIn('tls', node)
            self.assertEqual(None if network == 'both' else network, node.get('network'))
            self.assertEqual({'inbound': [node['tag']], 'action': 'route', 'outbound': 'direct'},
                             config['route']['rules'][-1])

    def test_invalid_values_do_not_write(self):
        self.manager.add_user('existing')
        before = self.store.path.read_bytes()
        for changes in ({'listen_port': True}, {'listen_port': 0}, {'target_port': 65536},
                        {'target': 'bad host'}, {'listen': 'example.com'}, {'network': 'quic'},
                        {'name': '\n'}, {'target': '127.0.0.1', 'target_port': 15353}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.manager.add_forward({**self.values, **changes})
            self.assertEqual(before, self.store.path.read_bytes())

    def test_conflicts_and_different_transports(self):
        self.manager.add_forward({**self.values, 'network': 'tcp'})
        self.manager.add_forward({**self.values, 'network': 'udp'})
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(ValidationError, '冲突'):
            self.manager.add_forward(self.values)
        with self.assertRaisesRegex(ValidationError, '冲突'):
            self.store.update(lambda state: state['inbounds'].update({
                'node': {'id': 'node', 'protocol': 'reality', 'settings': {'port': 15353}}}))
        self.assertEqual(before, self.store.path.read_bytes())

    def test_acme_port_reserved(self):
        self.store.update(lambda state: state['inbounds'].update({
            'node': {'id': 'node', 'protocol': 'hysteria2', 'settings': {'port': 443}}}))
        with self.assertRaisesRegex(ValidationError, '冲突'):
            self.manager.add_forward({**self.values, 'listen_port': 80})

    def test_old_state_remains_readable(self):
        self.manager.add_user('existing')
        self.assertNotIn('forwards', self.store.read())
        key = self.manager.add_forward(self.values)
        self.manager.delete_forward(key)
        self.assertEqual({}, self.store.read()['forwards'])
        self.assertEqual(1, len(self.store.read()['users']))

    def deploy(self):
        self.engine, self.service = Engine(), Service()
        self.deployment = Deployment(self.store, Path(self.temp.name) / 'config.json', self.engine, self.service)
        self.store.deployment = self.deployment
        self.store.update(lambda state: state.update(deployed=True))

    def test_rollback_and_delete_last_active_forward(self):
        key = self.manager.add_forward(self.values)
        self.deploy()
        before = self.store.path.read_bytes(), self.deployment.config_path.read_bytes()
        self.service.fail_once = True
        with self.assertRaises(ValidationError):
            self.manager.delete_forward(key)
        self.assertEqual(before, (self.store.path.read_bytes(), self.deployment.config_path.read_bytes()))
        self.manager.delete_forward(key)
        self.assertEqual([], json.loads(self.deployment.config_path.read_text())['inbounds'])

    def test_invalid_engine_check_preserves_state(self):
        self.manager.add_forward(self.values)
        self.deploy()
        before = self.store.path.read_bytes(), self.deployment.config_path.read_bytes()
        self.engine.fail = True
        with self.assertRaises(ValidationError):
            self.manager.add_forward({**self.values, 'listen_port': 15354})
        self.assertEqual(before, (self.store.path.read_bytes(), self.deployment.config_path.read_bytes()))

    def test_backup_restore(self):
        key = self.manager.add_forward(self.values)
        self.deploy()
        with self.store.locked():
            backup = self.deployment.backup()
        self.manager.delete_forward(key)
        with self.store.locked():
            self.deployment.restore(backup)
        self.assertIn(key, self.store.read()['forwards'])

    def test_cli_add_list_cancel_delete(self):
        answers = ['7', '2', 'DNS', '', '15353', '1.1.1.1', '53', '', '1',
                   '3', '1', 'n', '0', '0']
        output = io.StringIO()
        with patch('builtins.input', side_effect=answers), contextlib.redirect_stdout(output):
            self.assertEqual(0, run(self.manager, Mock(), Mock()))
        self.assertIn('TCP + UDP', output.getvalue())
        self.assertEqual(1, len(self.store.read()['forwards']))
        with patch('builtins.input', side_effect=['7', '3', '1', 'y', '0', '0']), \
                contextlib.redirect_stdout(io.StringIO()):
            run(self.manager, Mock(), Mock())
        self.assertEqual({}, self.store.read()['forwards'])

    @unittest.skipUnless(os.environ.get('SING_BOX_TEST_BINARY'), 'set SING_BOX_TEST_BINARY for official engine check')
    def test_official_engine(self):
        self.manager.add_forward(self.values)
        engine = SingBox(os.environ['SING_BOX_TEST_BINARY'])
        engine.version()
        candidate = Path(self.temp.name) / 'check.json'
        candidate.write_text(json.dumps(build(self.store.read())))
        engine.check(candidate)
