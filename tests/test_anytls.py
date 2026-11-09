import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, unquote, urlsplit

from sbmanager.cli import Cancelled, node_action
from sbmanager.core.config_builder import build
from sbmanager.core.state_manager import StateStore
from sbmanager.core.transaction_manager import Deployment
from sbmanager.core.validation import validate_state
from sbmanager.modules.certificate_manager import inspect
from sbmanager.modules.export_manager import export_user
from sbmanager.modules.manager import Manager
from sbmanager.modules.node_manager import ask_inbound_ports, configure
from sbmanager.security import ValidationError
from sbmanager.system.network import inbound_listeners
from test_deployment import Engine, Service


class AnyTLSTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / 'state')
        self.manager = Manager(self.store)
        self.engine = Mock()
        self.values = {'port': 443, 'public_port': 443, 'public_host': 'node.example',
                       'server_name': 'cert.example'}

    def add_node(self, name='AnyTLS', **values):
        return configure(self.manager, self.engine, None, {**self.values, **values},
                         name=name, protocol='anytls')

    def action(self, number, answers):
        output = io.StringIO()
        with patch('builtins.input', side_effect=answers), contextlib.redirect_stdout(output):
            node_action(number, self.manager, self.engine)
        return output.getvalue()

    def test_menu_add_edit_and_cancel_preserve_credentials(self):
        output = self.action(2, ['4', '', '', 'node.example', 'cert.example'])
        iid, node = next(iter(self.store.read()['inbounds'].items()))
        self.assertEqual('anytls', node['protocol'])
        self.assertEqual('AnyTLS', node['name'])
        self.assertEqual(self.values, node['settings'])
        self.assertNotIn('WebSocket 路径', output)
        self.assertNotIn('Rewrite port', output)
        uid = self.manager.add_user('Alice')
        self.manager.grant(uid, iid)
        before = self.store.read()['users']
        self.action(3, ['1', '2443', '', ''])
        state = self.store.read()
        self.assertEqual(before, state['users'])
        self.assertEqual(2443, state['inbounds'][iid]['settings']['port'])
        self.assertEqual(2443, state['inbounds'][iid]['settings']['public_port'])
        self.engine.keypair.assert_not_called()
        with self.assertRaises(Cancelled):
            self.action(2, ['4', '', '0'])
        self.assertEqual(state, self.store.read())

    def test_default_port_is_tcp_443(self):
        ask = Mock(return_value='')
        self.assertEqual({'port': 443, 'public_port': 443}, ask_inbound_ports(ask, 'anytls'))
        ask.assert_called_once()
        self.assertIn('TCP', ask.call_args.args[0])

    def test_password_generation_reset_and_summary_redaction(self):
        iid = self.manager.add_inbound('AnyTLS', 'anytls')
        alice = self.manager.add_user_all('Alice')
        bob = self.manager.add_user('Bob')
        self.manager.grant(bob, iid)
        state = self.store.read()
        first = state['users'][alice]['grants'][iid]
        second = state['users'][bob]['grants'][iid]
        self.assertRegex(first, r'^[A-Za-z0-9_-]{32}$')
        self.assertNotEqual(first, second)
        summary = json.dumps(self.manager.summary())
        self.assertNotIn(first, summary)
        self.assertNotIn(second, summary)
        self.manager.reset_credential(alice, iid)
        self.assertNotEqual(first, self.store.read()['users'][alice]['grants'][iid])
        self.assertEqual(second, self.store.read()['users'][bob]['grants'][iid])

    def test_server_config_uses_password_auth_and_shared_acme(self):
        iid = self.add_node()
        other = configure(self.manager, self.engine, None, {**self.values, 'port': 8443,
                          'public_port': 8443, 'path': '/proxy'}, name='WebSocket', protocol='cloudflare_ws')
        alice = self.manager.add_user('Alice')
        bob = self.manager.add_user('Bob')
        self.manager.grant(alice, iid)
        self.manager.grant(bob, other)
        self.manager.grant(bob, iid)
        self.manager.set_enabled(bob, False)
        state = self.store.read()
        config = build(state)
        node = config['inbounds'][0]
        self.assertEqual({'type': 'anytls', 'tag': iid, 'listen': '::', 'listen_port': 443,
                          'users': [{'name': alice, 'password': state['users'][alice]['grants'][iid]}],
                          'tls': {'enabled': True, 'server_name': 'cert.example',
                                  'certificate_provider': 'managed-acme'}}, node)
        self.assertEqual(['cert.example'], config['certificate_providers'][0]['domain'])
        self.assertTrue(config['certificate_providers'][0]['disable_tls_alpn_challenge'])
        self.assertNotIn('padding_scheme', node)
        self.assertEqual([('tcp', '::', 443), ('tcp', '::', 8443)], list(inbound_listeners(config)))
        with patch('sbmanager.modules.certificate_manager.socket.getaddrinfo', return_value=[]):
            report = inspect(state, self.temp.name)
        self.assertEqual(['cert.example'], [item['domain'] for item in report['domains']])

    def test_export_password_uri_encoding_ipv6_and_user_isolation(self):
        iid = self.add_node(name='AnyTLS 测试 #1', public_host='2001:db8::1',
                            port=2443, public_port=9443)
        alice = self.manager.add_user('Alice')
        bob = self.manager.add_user('Bob')
        self.manager.grant(alice, iid)
        self.manager.grant(bob, iid)
        password = 'p@ss:/?#% +中文'
        self.store.update(lambda state: state['users'][alice]['grants'].update({iid: password}))
        state = self.store.read()
        exported = export_user(state, alice)
        node = exported['config']['outbounds'][1]
        self.assertEqual({'type': 'anytls', 'tag': iid, 'server': '2001:db8::1',
                          'server_port': 9443, 'password': password,
                          'tls': {'enabled': True, 'server_name': 'cert.example'}}, node)
        uri = urlsplit(exported['links'][0])
        self.assertEqual('anytls', uri.scheme)
        self.assertEqual(password, unquote(uri.username))
        self.assertEqual('2001:db8::1', uri.hostname)
        self.assertEqual(9443, uri.port)
        self.assertEqual('/', uri.path)
        self.assertEqual({'sni': ['cert.example']}, parse_qs(uri.query))
        self.assertEqual('AnyTLS 测试 #1', unquote(uri.fragment))
        self.assertNotIn(state['users'][bob]['grants'][iid], json.dumps(exported))
        self.manager.set_enabled(alice, False)
        with self.assertRaises(ValidationError):
            export_user(self.store.read(), alice)
        self.manager.set_enabled(alice, True)
        self.manager.revoke(alice, iid)
        with self.assertRaises(ValidationError):
            export_user(self.store.read(), alice)

    def test_per_user_routes_block_udp_only_for_tcp_only_egress(self):
        iid = self.add_node()
        alice = self.manager.add_user('Alice')
        bob = self.manager.add_user('Bob')
        self.manager.grant(alice, iid)
        self.manager.grant(bob, iid)
        for udp in (False, True):
            with self.subTest(udp=udp):
                eid = self.manager.save_egress('proxy', 'socks5', {'server': 'proxy.example',
                      'port': 1080, 'username': '', 'password': '', 'udp': udp})
                self.manager.bind(alice, iid, eid)
                rules = build(self.store.read())['route']['rules']
                expected = [] if udp else [{'inbound': [iid], 'auth_user': [alice],
                                           'network': 'udp', 'action': 'reject'}]
                expected.append({'inbound': [iid], 'auth_user': [alice],
                                 'action': 'route', 'outbound': eid})
                self.assertEqual(expected, rules)
        self.manager.bind(alice, iid, None)
        self.assertEqual([], build(self.store.read())['route']['rules'])

    def test_tcp_port_conflicts_but_udp_same_port_allowed(self):
        self.add_node()
        configure(self.manager, self.engine, None, self.values, name='Hysteria2', protocol='hysteria2')
        self.assertEqual(2, len(build(self.store.read())['inbounds']))
        state = self.store.read()
        duplicate = copy.deepcopy(next(iter(state['inbounds'].values())))
        state['inbounds']['duplicate'] = {**duplicate, 'id': 'duplicate'}
        with self.assertRaises(ValidationError):
            build(state)
        for port in (443, 80):
            with self.subTest(port=port), self.assertRaises(ValidationError):
                self.manager.add_forward({'name': 'forward', 'listen_port': port,
                                          'target': 'target.example', 'target_port': 8080, 'network': 'tcp'})
        validate_state(self.store.read())

    def test_invalid_node_values_do_not_write(self):
        self.manager.add_user('existing')
        before = self.store.path.read_bytes()
        for changes in ({'port': 0}, {'public_port': 65536}, {'port': True},
                        {'public_host': 'bad host'}, {'server_name': 'bad host'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.add_node(**changes)
            self.assertEqual(before, self.store.path.read_bytes())

    def test_deployment_failure_rolls_back_node_config_and_password(self):
        iid = self.add_node()
        uid = self.manager.add_user_all('Alice')
        service = Service()
        self.store.deployment = Deployment(self.store, Path(self.temp.name) / 'config.json', Engine(), service)
        self.store.update(lambda state: state.update(deployed=True))
        state_before = self.store.path.read_bytes()
        config_before = self.store.deployment.config_path.read_bytes()
        service.fail_once = True
        with self.assertRaises(ValidationError):
            configure(self.manager, self.engine, iid, {**self.values, 'port': 2443, 'public_port': 2443})
        self.assertEqual(state_before, self.store.path.read_bytes())
        self.assertEqual(config_before, self.store.deployment.config_path.read_bytes())
        service.fail_once = True
        with self.assertRaises(ValidationError):
            self.manager.reset_credential(uid, iid)
        self.assertEqual(state_before, self.store.path.read_bytes())
        self.assertEqual(config_before, self.store.deployment.config_path.read_bytes())
        self.assertTrue(service.running)

    def test_delete_node_cleans_only_its_grants_and_bindings(self):
        iid = self.add_node()
        other = self.add_node(name='other', port=2443, public_port=2443)
        uid = self.manager.add_user_all('Alice')
        self.manager.bind(uid, iid, None)
        self.manager.bind(uid, other, None)
        self.manager.delete_inbound(iid)
        state = self.store.read()
        self.assertEqual({other}, set(state['users'][uid]['grants']))
        self.assertEqual({f'{uid}:{other}'}, set(state['bindings']))
