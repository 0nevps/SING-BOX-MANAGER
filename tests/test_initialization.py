import contextlib
import io
import tempfile
import unittest
from unittest.mock import Mock, patch

from sbmanager.core.state_manager import StateStore
from sbmanager.modules.initialization import wizard
from sbmanager.modules.manager import Manager


class InitializationSelectionTests(unittest.TestCase):
    def run_wizard(self, answers):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        manager = Manager(StateStore(directory.name))
        engine = Mock()
        engine.keypair.return_value = ('private', 'public')
        ask = Mock(side_effect=answers)
        output = io.StringIO()
        with patch('sbmanager.system.network.public_addresses', return_value={}) as addresses, \
             patch('sbmanager.modules.initialization.check_reality_target', return_value='TLS 检查通过') as probe, \
             patch('sbmanager.modules.initialization.socket.getaddrinfo') as dns, \
             contextlib.redirect_stdout(output):
            wizard(manager, engine, ask)
        return manager, engine, ask, output.getvalue(), addresses, probe, dns

    def test_select_one_protocol_only_collects_its_settings(self):
        cases = [
            ('reality', ['1', 'proxy.example', '', 'target.example', '', '', 'yes']),
            ('hysteria2', ['2', '', 'hy.example', '', 'yes']),
            ('cloudflare_ws', ['3', '', 'ws.example', '', '2', '', 'yes']),
        ]
        for protocol, answers in cases:
            with self.subTest(protocol=protocol):
                manager, engine, ask, output, addresses, probe, dns = self.run_wizard(answers)
                state = manager.store.read()
                self.assertEqual([protocol], [node['protocol'] for node in state['inbounds'].values()])
                user = next(iter(state['users'].values()))
                self.assertEqual(set(state['inbounds']), set(user['grants']))
                self.assertEqual('default', user['name'])
                self.assertFalse(state.get('deployed'))
                self.assertEqual(len(answers), ask.call_count)
                self.assertEqual(protocol == 'reality', engine.keypair.called)
                self.assertEqual(protocol == 'reality', probe.called)
                self.assertEqual(protocol == 'reality', addresses.called)
                self.assertEqual(protocol != 'reality', dns.called)
                self.assertEqual(protocol != 'reality', '证书验证需要' in output)
                self.assertEqual(protocol == 'cloudflare_ws', 'WebSocket 路径:' in output)

    def test_select_subset_deduplicates_and_skips_reality(self):
        manager, engine, _, _, addresses, probe, dns = self.run_wizard(
            ['3,2,3', 'Alice', 'hy.example', 'ws.example', '/custom', '', '2', '9443', 'yes'])
        state = manager.store.read()
        self.assertEqual(['hysteria2', 'cloudflare_ws'],
                         [node['protocol'] for node in state['inbounds'].values()])
        self.assertEqual(2, len(next(iter(state['users'].values()))['grants']))
        engine.keypair.assert_not_called()
        addresses.assert_not_called()
        probe.assert_not_called()
        self.assertEqual(2, dns.call_count)

    def test_empty_invalid_and_zero_selection_never_installs_defaults(self):
        manager, engine, ask, output, addresses, probe, dns = self.run_wizard(
            ['', '4', '1 x', '0 2', '0'])
        self.assertEqual(5, ask.call_count)
        self.assertIn('请选择节点编号', output)
        self.assertFalse(manager.store.path.exists())
        engine.version.assert_not_called()
        engine.keypair.assert_not_called()
        addresses.assert_not_called()
        probe.assert_not_called()
        dns.assert_not_called()

    def test_declining_save_keeps_state_empty(self):
        manager, _, _, _, _, _, _ = self.run_wizard(['2', '', 'hy.example', '', 'no'])
        self.assertFalse(manager.store.path.exists())
