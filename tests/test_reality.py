import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch

from sbmanager.core.state_manager import StateStore
from sbmanager.modules.manager import Manager
from sbmanager.modules.node_manager import configure, websocket_path
from sbmanager.security import ValidationError
from sbmanager.system.network import check_reality_target


class RealityTests(unittest.TestCase):
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
