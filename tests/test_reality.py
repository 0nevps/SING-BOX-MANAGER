import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from sbmanager.core.state_manager import StateStore
from sbmanager.modules.manager import Manager
from sbmanager.modules.node_manager import ask_reality_names, configure, websocket_path
from sbmanager.modules.initialization import wizard
from sbmanager.modules.export_manager import export_user
from sbmanager.security import ValidationError
from sbmanager.system.network import check_reality_target


class RealityTests(unittest.TestCase):
    def test_default_and_explicit_sni(self):
        for answer, expected in [('', 'target.example'), ('alt.example', 'alt.example')]:
            ask = Mock(side_effect=['target.example', answer])
            self.assertEqual(('target.example', expected), ask_reality_names(ask))

    def test_tls13_and_hostname_verification(self):
        context = ssl.create_default_context()
        with patch('ssl.create_default_context', return_value=context), \
             patch('socket.create_connection') as connect, \
             patch.object(context, 'wrap_socket') as wrap:
            wrap.return_value.__enter__.return_value.version.return_value = 'TLSv1.3'
            self.assertIn('仍需 REALITY', check_reality_target('target.example', 'sni.example'))
            connect.assert_called_once_with(('target.example', 443), timeout=5)
            self.assertEqual('sni.example', wrap.call_args.kwargs['server_hostname'])
            self.assertTrue(context.check_hostname)
            self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
            self.assertEqual(ssl.TLSVersion.TLSv1_3, context.minimum_version)
            self.assertEqual(ssl.TLSVersion.TLSv1_3, context.maximum_version)

    def test_failures_have_actionable_messages(self):
        for failure, message in [(ssl.SSLCertVerificationError('bad cert'), '证书校验失败'),
                                 (ssl.SSLError('protocol'), 'TLS 1.3 握手失败'),
                                 (TimeoutError(), '连接失败')]:
            with self.subTest(message=message), patch('socket.create_connection', side_effect=failure):
                with self.assertRaisesRegex(ValidationError, message):
                    check_reality_target('target.example', 'sni.example')

    def test_configure_default_and_failed_edit_preserves_state(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(StateStore(directory))
            iid = manager.add_inbound('Reality', 'reality')
            engine = Mock()
            engine.keypair.return_value = ('private', 'public')
            values = {'port': 443, 'public_port': 443, 'public_host': 'proxy.example', 'handshake': 'target.example'}
            with patch('sbmanager.modules.node_manager.check_reality_target') as probe:
                configure(manager, engine, iid, values)
                probe.assert_called_once_with('target.example', 'target.example', 443)
            before = manager.store.path.read_bytes()
            with patch('sbmanager.modules.node_manager.check_reality_target', side_effect=ValidationError('failed')):
                with self.assertRaises(ValidationError):
                    configure(manager, engine, iid, dict(values, server_name='other.example'))
            self.assertEqual(before, manager.store.path.read_bytes())
            engine.keypair.assert_called_once()

    def test_wizard_probe_failure_does_not_save(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(StateStore(directory))
            ask = Mock(side_effect=['1', 'proxy.example', 'Alice', 'target.example', ''])
            with patch('sbmanager.system.network.public_addresses', return_value={}), \
                 patch('sbmanager.modules.initialization.check_reality_target', side_effect=ValidationError('failed')):
                with self.assertRaises(ValidationError):
                    wizard(manager, Mock(), ask)
            self.assertFalse(manager.store.path.exists())

    def test_wizard_defaults_first_username_and_accepts_custom_name(self):
        paths = set()
        for answer, expected in [('', 'default'), ('Alice', 'Alice')]:
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as directory:
                manager = Manager(StateStore(directory))
                engine = Mock()
                engine.keypair.return_value = ('private', 'public')
                ask = Mock(side_effect=[
                    '1 2 3', 'proxy.example', answer, 'target.example', '', 'hy.example',
                    'ws.example', '', '', '', '', '', 'yes',
                ])
                with patch('sbmanager.system.network.public_addresses', return_value={}), \
                     patch('sbmanager.modules.initialization.check_reality_target', return_value='TLS 检查通过'), \
                     patch('sbmanager.modules.initialization.socket.getaddrinfo'):
                    wizard(manager, engine, ask)
                users = list(manager.store.read()['users'].values())
                self.assertEqual(1, len(users))
                self.assertEqual(expected, users[0]['name'])
                self.assertEqual(3, len(users[0]['grants']))
                self.assertEqual(3, len(manager.store.read()['inbounds']))
                self.assertIn('默认 default', ask.call_args_list[2].args[0])
                self.assertEqual(13, ask.call_count)
                ports = {i['protocol']: (i['settings']['port'], i['settings']['public_port'])
                         for i in manager.store.read()['inbounds'].values()}
                self.assertEqual({'reality': (443, 443), 'hysteria2': (443, 443),
                                  'cloudflare_ws': (8443, 443)}, ports)
                ws_inbound = next(i for i in manager.store.read()['inbounds'].values()
                                  if i['protocol'] == 'cloudflare_ws')
                path = ws_inbound['settings']['path']
                self.assertRegex(path, r'^/[A-Za-z0-9_-]{22}$')
                self.assertNotEqual('/gateway', path)
                paths.add(path)
                exported = export_user(manager.store.read(), users[0]['id'])
                self.assertEqual(path, parse_qs(urlparse(exported['links'][2]).query)['path'][0])
                self.assertEqual(path, exported['config']['outbounds'][3]['transport']['path'])
        self.assertEqual(2, len(paths))

    def test_wizard_can_customize_ports(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(StateStore(directory))
            engine = Mock()
            engine.keypair.return_value = ('private', 'public')
            ask = Mock(side_effect=[
                '1 2 3', 'proxy.example', '', 'target.example', '', 'hy.example',
                'ws.example', '', '2443', '5443', '1', '8444', 'yes',
            ])
            with patch('sbmanager.system.network.public_addresses', return_value={}), \
                 patch('sbmanager.modules.initialization.check_reality_target', return_value='TLS 检查通过'), \
                 patch('sbmanager.modules.initialization.socket.getaddrinfo'):
                wizard(manager, engine, ask)
            ports = {i['protocol']: (i['settings']['port'], i['settings']['public_port'])
                     for i in manager.store.read()['inbounds'].values()}
            self.assertEqual({'reality': (2443, 2443), 'hysteria2': (5443, 5443),
                              'cloudflare_ws': (8444, 443)}, ports)

    def test_wizard_direct_websocket_uses_one_port(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(StateStore(directory))
            engine = Mock()
            engine.keypair.return_value = ('private', 'public')
            ask = Mock(side_effect=[
                '1 2 3', 'proxy.example', '', 'target.example', '', 'hy.example',
                'ws.example', '', '2443', '5443', '2', '8444', 'yes',
            ])
            with patch('sbmanager.system.network.public_addresses', return_value={}), \
                 patch('sbmanager.modules.initialization.check_reality_target', return_value='TLS 检查通过'), \
                 patch('sbmanager.modules.initialization.socket.getaddrinfo'):
                wizard(manager, engine, ask)
            ports = {i['protocol']: (i['settings']['port'], i['settings']['public_port'])
                     for i in manager.store.read()['inbounds'].values()}
            self.assertEqual({'reality': (2443, 2443), 'hysteria2': (5443, 5443),
                              'cloudflare_ws': (8444, 8444)}, ports)
            state = manager.store.read()
            user = next(iter(state['users'].values()))
            exported = export_user(state, user['id'])
            self.assertEqual(8444, exported['config']['outbounds'][3]['server_port'])
            self.assertEqual(8444, urlparse(exported['links'][2]).port)

    def test_websocket_path_generation_reuse_and_override(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(StateStore(directory))
            iid = manager.add_inbound('WebSocket', 'cloudflare_ws')
            settings = {'port': 8443, 'public_port': 443,
                        'public_host': 'ws.example', 'server_name': 'ws.example'}
            configure(manager, None, iid, settings)
            first = manager.store.read()['inbounds'][iid]['settings']['path']
            self.assertRegex(first, r'^/[A-Za-z0-9_-]{22}$')
            configure(manager, None, iid, settings)
            self.assertEqual(first, manager.store.read()['inbounds'][iid]['settings']['path'])
            configure(manager, None, iid, dict(settings, path='/custom'))
            self.assertEqual('/custom', manager.store.read()['inbounds'][iid]['settings']['path'])
            configure(manager, None, iid, settings)
            self.assertEqual('/custom', manager.store.read()['inbounds'][iid]['settings']['path'])
            with self.assertRaises(ValidationError):
                websocket_path('/bad?query')
