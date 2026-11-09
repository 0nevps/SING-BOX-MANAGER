import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from sbmanager.core.config_builder import build
from sbmanager.core.state_manager import StateStore
from sbmanager.core.transaction_manager import Deployment, atomic_write, encode
from sbmanager.modules.manager import Manager
from sbmanager.modules.export_manager import export_user
from sbmanager.security import ValidationError
from sbmanager.system.singbox import SingBox


class Engine:
    fail = False
    def version(self): return '1.14.4'
    def check(self, path):
        if self.fail: raise ValidationError('invalid')
        json.loads(Path(path).read_text())


class Service:
    running = False
    fail_once = False
    def active(self): return self.running
    def restart(self):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError('service failed')
        self.running = True
    def stop(self): self.running = False
    def health(self, config):
        if not self.running: raise RuntimeError('not running')


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / 'state')
        self.manager = Manager(self.store)
        self.user = self.manager.add_user('Alice')
        self.inbound = self.manager.add_inbound('Reality', 'reality')
        self.manager.grant(self.user, self.inbound)
        def setup(state):
            state['inbounds'][self.inbound]['settings'] = {'port': 1443, 'public_port': 1443,
                'public_host': 'example.com', 'server_name': 'example.com', 'handshake': 'example.com',
                'private_key': 'EPkO3Cq2YtGCxO-qPTGR8RLRoY2lgKiu_Vc4OghYCl0',
                'public_key': 'X_oi3zE-6V6vX6wtnGbtJg4o8PaiVI8VE2hQdBDiWzk', 'short_id': 'abcdef0123456789'}
        self.store.update(setup)
        self.engine, self.service = Engine(), Service()
        self.deployment = Deployment(self.store, Path(self.temp.name) / 'config.json', self.engine, self.service)
        self.store.deployment = self.deployment

    def activate(self):
        self.store.update(lambda state: state.update(deployed=True))

    def test_apply_and_rollback_both_files(self):
        self.activate()
        state_before = self.store.path.read_bytes()
        config_before = self.deployment.config_path.read_bytes()
        self.service.fail_once = True
        with self.assertRaises(ValidationError):
            self.manager.set_enabled(self.user, False)
        self.assertEqual(state_before, self.store.path.read_bytes())
        self.assertEqual(config_before, self.deployment.config_path.read_bytes())
        self.assertTrue(self.service.running)
        self.assertFalse(self.deployment.journal.exists())

    def test_invalid_config_preserves_both_files(self):
        self.activate()
        before = self.store.path.read_bytes()
        self.engine.fail = True
        with self.assertRaises(ValidationError): self.manager.delete_user(self.user)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_failed_first_deployment_restores_undeployed_state(self):
        before = self.store.path.read_bytes()
        self.service.fail_once = True
        with self.assertRaises(ValidationError): self.activate()
        self.assertFalse(self.deployment.config_path.exists())
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertFalse(self.service.running)

    def test_pending_journal_recovered_before_next_read(self):
        self.activate()
        before = self.store.read()
        atomic_write(self.deployment.journal, encode(self.deployment.snapshot()))
        atomic_write(self.store.path, encode({'schema_version': 99}))
        self.assertEqual(before, self.store.read())

    def test_tcp_only_blocks_udp_before_proxy_rule(self):
        eid = self.manager.save_egress('proxy', 'socks5', {'server': 'localhost', 'port': 1080,
                                                       'username': 'u', 'password': 'p', 'udp': False})
        self.manager.bind(self.user, self.inbound, eid)
        rules = build(self.store.read())['route']['rules']
        self.assertEqual('reject', rules[0]['action'])
        self.assertEqual('udp', rules[0]['network'])
        self.assertEqual([self.user], rules[0]['auth_user'])
        self.assertEqual([self.inbound], rules[0]['inbound'])
        self.assertEqual(eid, rules[1]['outbound'])

    def test_disabled_user_absent_from_config_and_export(self):
        self.manager.set_enabled(self.user, False)
        self.assertEqual([], build(self.store.read())['inbounds'][0]['users'])
        with self.assertRaises(ValidationError): export_user(self.store.read(), self.user)

    def test_export_excludes_other_user_and_private_key(self):
        bob = self.manager.add_user('Bob')
        self.manager.grant(bob, self.inbound)
        state = self.store.read()
        result = json.dumps(export_user(state, self.user))
        self.assertNotIn(state['users'][bob]['grants'][self.inbound], result)
        self.assertNotIn(state['inbounds'][self.inbound]['settings']['private_key'], result)

    def test_port_conflict_rejected(self):
        state = self.store.read()
        state['inbounds']['duplicate'] = copy.deepcopy(state['inbounds'][self.inbound])
        with self.assertRaises(ValidationError): build(state)

    def test_backup_restore(self):
        self.activate()
        with self.store.locked(): name = self.deployment.backup()
        self.manager.set_enabled(self.user, False)
        with self.store.locked(): self.deployment.restore(name)
        self.assertTrue(self.store.read()['users'][self.user]['enabled'])

    @unittest.skipUnless(os.environ.get('SING_BOX_TEST_BINARY'), 'set SING_BOX_TEST_BINARY for official engine check')
    def test_official_engine_server_and_client(self):
        engine = SingBox(os.environ['SING_BOX_TEST_BINARY'])
        engine.version()
        state = self.store.read()
        for protocol, port in [('hysteria2', 1443), ('cloudflare_ws', 8443), ('anytls', 2443)]:
            iid = self.manager.add_inbound(protocol, protocol)
            self.manager.grant(self.user, iid)
            def setup(current):
                current['inbounds'][iid]['settings'] = {'port': port, 'public_port': port, 'public_host': 'example.com',
                                                      'server_name': 'example.com', 'path': '/gateway'}
            self.store.update(setup)
        state = self.store.read()
        candidate = Path(self.temp.name) / 'check.json'
        atomic_write(candidate, encode(build(state, str(Path(self.temp.name) / 'acme'))))
        engine.check(candidate)
        atomic_write(candidate, encode(export_user(state, self.user)['config']))
        engine.check(candidate)
