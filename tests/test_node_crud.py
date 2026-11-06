import contextlib
import io
import tempfile
import unittest
from unittest.mock import Mock, patch

from sbmanager.cli import Cancelled, node_action
from sbmanager.core.state_manager import StateStore
from sbmanager.modules.manager import Manager
from sbmanager.modules.node_manager import configure


class NodeCrudTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = StateStore(directory.name)
        self.manager = Manager(self.store)
        self.engine = Mock()
        self.engine.keypair.return_value = ('private', 'public')

    def action(self, number, answers):
        with patch('builtins.input', side_effect=answers), contextlib.redirect_stdout(io.StringIO()):
            node_action(number, self.manager, self.engine)

    def test_complete_add_defaults_and_edit_preserves_name_and_values(self):
        self.action(2, ['2', '', '', 'node.example', ''])
        iid, node = next(iter(self.store.read()['inbounds'].items()))
        self.assertEqual('Hysteria2', node['name'])
        self.assertEqual(443, node['settings']['port'])
        self.action(3, ['1', '', '', ''])
        self.assertEqual(node, self.store.read()['inbounds'][iid])
        self.action(2, ['2', '', '8443', 'other.example', ''])
        self.assertEqual(['Hysteria2', 'Hysteria2 2'],
                         [n['name'] for n in self.store.read()['inbounds'].values()])

    def test_cancel_and_invalid_add_leave_no_partial_node(self):
        for answers in (['2', '0'], ['2', '', '0'], ['2', '', '', '0']):
            with self.assertRaises(Cancelled):
                self.action(2, answers)
            self.assertEqual({}, self.store.read()['inbounds'])
        with self.assertRaises(ValueError):
            self.action(2, ['2', '', '', 'invalid host', ''])
        self.assertEqual({}, self.store.read()['inbounds'])

    def test_reality_probe_failure_leaves_no_node(self):
        with patch('sbmanager.modules.node_manager.check_reality_target', side_effect=ValueError('failed')):
            with self.assertRaises(ValueError):
                self.action(2, ['1', '', '', 'node.example', 'target.example', ''])
        self.assertEqual({}, self.store.read()['inbounds'])

    def test_delete_confirmation_cleans_only_selected_node(self):
        self.action(2, ['2', '', '', 'node.example', ''])
        iid = next(iter(self.store.read()['inbounds']))
        other = self.manager.add_inbound('other', 'reality')
        uid = self.manager.add_user('user')
        self.manager.grant(uid, iid)
        self.manager.grant(uid, other)
        self.manager.bind(uid, iid, None)
        self.manager.bind(uid, other, None)
        before = self.store.read()
        self.action(4, ['1', 'no'])
        self.assertEqual(before, self.store.read())
        self.action(4, ['1', 'y'])
        state = self.store.read()
        self.assertNotIn(iid, state['inbounds'])
        self.assertEqual({other}, set(state['users'][uid]['grants']))
        self.assertEqual({f'{uid}:{other}'}, set(state['bindings']))

    def test_protocol_change_is_rejected_without_mutation(self):
        self.action(2, ['2', '', '', 'node.example', ''])
        iid = next(iter(self.store.read()['inbounds']))
        uid = self.manager.add_user('user')
        self.manager.grant(uid, iid)
        self.manager.bind(uid, iid, None)
        before = self.store.read()
        with self.assertRaisesRegex(ValueError, '协议不可修改'):
            configure(self.manager, self.engine, iid, {}, protocol='cloudflare_ws')
        self.assertEqual(before, self.store.read())
        self.action(3, ['1', '8443', '', ''])
        state = self.store.read()
        self.assertEqual('Hysteria2', state['inbounds'][iid]['name'])
        self.assertEqual('hysteria2', state['inbounds'][iid]['protocol'])
        self.assertEqual(8443, state['inbounds'][iid]['settings']['port'])
        self.assertEqual(before['users'], state['users'])
        self.assertEqual(before['bindings'], state['bindings'])

    def test_view_links_match_export_and_exclude_disabled_users(self):
        from sbmanager.modules.export_manager import export_user
        for protocol in ('reality', 'hysteria2', 'cloudflare_ws'):
            values = dict(port=443, public_port=443, public_host='2001:db8::1',
                          handshake='target.example', server_name='target.example', path='/test')
            with patch('sbmanager.modules.node_manager.check_reality_target'):
                iid = configure(self.manager, self.engine, None, values, name=protocol, protocol=protocol)
            uid = self.manager.add_user(protocol)
            self.manager.grant(uid, iid)
            # An unrelated unfinished node must not prevent this link from displaying.
            unfinished = self.manager.add_inbound(protocol + '-unfinished', protocol)
            self.manager.grant(uid, unfinished)
            disabled = self.manager.add_user(protocol + '-disabled')
            self.manager.grant(disabled, iid)
            self.manager.set_enabled(disabled, False)
            state = self.store.read()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                node_action(1, self.manager, self.engine)
            self.assertIn(export_user(state, uid, iid)['links'][0], output.getvalue())
            self.assertNotIn(state['users'][disabled]['grants'][iid], output.getvalue())
            self.assertIn('分享链接含连接密钥', output.getvalue())
            self.assertIn('节点未配置完整', output.getvalue())

    def test_view_without_granted_users_has_no_link(self):
        self.action(2, ['2', '', '', 'node.example', ''])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            node_action(1, self.manager, self.engine)
        self.assertIn('无已启用的授权用户', output.getvalue())
        self.assertNotIn('hysteria2://', output.getvalue())

    def test_add_is_one_complete_transaction(self):
        with patch.object(self.store, 'update', wraps=self.store.update) as update:
            self.action(2, ['2', '', '', 'node.example', ''])
        self.assertEqual(1, update.call_count)

    def test_failed_deployment_does_not_save_new_node(self):
        self.store.update(lambda state: state.update(deployed=True))
        before = self.store.path.read_bytes()
        self.store.deployment = Mock()
        self.store.deployment.apply.side_effect = ValueError('invalid configuration')
        with self.assertRaises(ValueError):
            self.action(2, ['2', '', '', 'node.example', ''])
        self.assertEqual(before, self.store.path.read_bytes())
        candidate = self.store.deployment.apply.call_args.args[0]
        self.assertEqual('node.example', next(iter(candidate['inbounds'].values()))['settings']['public_host'])

    def test_reality_edit_preserves_keys(self):
        values = dict(port=443, public_port=443, public_host='node.example',
                      handshake='target.example', server_name='target.example')
        with patch('sbmanager.modules.node_manager.check_reality_target'):
            iid = configure(self.manager, self.engine, None, values, name='node', protocol='reality')
            before = self.store.read()['inbounds'][iid]['settings']
            configure(self.manager, self.engine, iid, values)
        self.assertEqual(before, self.store.read()['inbounds'][iid]['settings'])
        self.engine.keypair.assert_called_once()
