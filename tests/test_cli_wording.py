"""Exercise named selections, concise guidance, and safe menu operations."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sbmanager.cli import run
from sbmanager.core.state_manager import StateStore
from sbmanager.modules.manager import Manager


class CliWordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / 'state')
        self.manager = Manager(self.store)
        self.user = self.manager.add_user('Alice')
        self.node = self.manager.add_inbound('REALITY', 'reality')
        self.manager.grant(self.user, self.node)

    def run_menu(self, answers, deployment=None):
        deployment = deployment if deployment is not None else Mock()
        output = io.StringIO()
        with patch('builtins.input', side_effect=answers) as reader, contextlib.redirect_stdout(output):
            result = run(self.manager, Mock(), deployment)
        self.assertEqual(0, result)
        prompts = '\n'.join(call.args[0] for call in reader.call_args_list)
        return output.getvalue(), prompts

    def add_proxy(self):
        return self.manager.save_egress('proxy', 'socks5', {
            'server': 'proxy.example.com', 'port': 1080,
            'username': 'alice', 'password': 'secret', 'udp': False})

    def test_network_menu_rejects_removed_help_option(self):
        before = self.store.path.read_bytes()
        output, prompts = self.run_menu(['7', '3', '0', '0'])
        self.assertNotIn('术语帮助', output)
        self.assertNotIn('独立的连接身份', output)
        self.assertIn('编号无效', output)
        self.assertIn('请选择 [0-2]', prompts)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_service_status_uses_connected_service(self):
        before = self.store.path.read_bytes()
        deployment = Mock()
        deployment.service.active.return_value = True
        output, _ = self.run_menu(['5', '1', '0', '0'], deployment)
        self.assertEqual(3, deployment.service.active.call_count)
        self.assertIn('服务运行中', output)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_delete_cancellation_warns_and_preserves_data(self):
        before = self.store.path.read_bytes()
        _, prompts = self.run_menu(['2', '8', '1', 'no', '0', '0'])
        self.assertIn('删除后无法直接撤销', prompts)
        self.assertIn('全部节点权限和出口设置', prompts)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_reset_requires_confirmation_and_invalidates_old_credential(self):
        before = self.store.read()['users'][self.user]['grants'][self.node]
        _, prompts = self.run_menu(['2', '7', '1', '1', 'no', '7', '1', '1', 'y', '0', '0'])
        self.assertIn('旧连接密钥将失效', prompts)
        self.assertIn('节点管理 > 查看节点', prompts)
        self.assertIn('获取新分享链接并更新客户端', prompts)
        self.assertNotEqual(before, self.store.read()['users'][self.user]['grants'][self.node])

    def test_direct_is_explicit_and_keeps_saved_egress(self):
        egress = self.add_proxy()
        self.manager.bind(self.user, self.node, egress)
        output, prompts = self.run_menu(['3', '5', '1', '1', '', '1', '0', '0'])
        self.assertIn('1 直连（DIRECT）', output)
        self.assertIn('编号无效', output)
        self.assertNotIn('ID', prompts)
        binding = self.store.read()['bindings'][f'{self.user}:{self.node}']
        self.assertIsNone(binding['active'])
        self.assertEqual([egress], binding['saved'])

    def test_restore_cancellation_warns_and_does_not_restore(self):
        deployment = Mock()
        deployment.backups = Path(self.temp.name) / 'backups'
        deployment.backups.mkdir()
        (deployment.backups / 'backup.json').touch()
        output, prompts = self.run_menu(['6', '3', '1', 'no', '0', '0'], deployment)
        self.assertIn('backup.json', output)
        self.assertIn('替换当前用户、节点、出口和配置，并重启服务', prompts)
        self.assertIn('当前设置会另存备份', prompts)
        deployment.restore.assert_not_called()

    def test_upgrade_cancellation_warns_and_does_not_upgrade(self):
        with patch('sbmanager.system.kernel.upgrade') as upgrade:
            _, prompts = self.run_menu(['8', '2', '1.14.4', 'no', '0', '0'], Mock())
        self.assertIn('连接可能短暂中断', prompts)
        self.assertIn('不加 v', prompts)
        upgrade.assert_not_called()

    def test_enable_and_disable_use_numbered_choices(self):
        _, prompts = self.run_menu(['2', '4', '1', '2', '0', '0'])
        self.assertFalse(self.store.read()['users'][self.user]['enabled'])
        self.assertNotIn('enable', prompts)
        self.run_menu(['2', '4', '1', '1', '0', '0'])
        self.assertTrue(self.store.read()['users'][self.user]['enabled'])

    def test_duplicate_username_explains_how_to_continue(self):
        before = self.store.path.read_bytes()
        output, _ = self.run_menu(['2', '2', 'Alice', '0', '0'])
        self.assertIn('这个用户名已存在，请换一个名称', output)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_cancel_object_selection_keeps_current_submenu_and_state(self):
        before = self.store.path.read_bytes()
        output, _ = self.run_menu(['2', '8', '0', '0', '0'])
        self.assertIn('Alice · 启用', output)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertNotIn('删除后无法', output)

    def test_empty_selection_returns_without_error(self):
        output, _ = self.run_menu(['3', '7', '0', '0'])
        self.assertIn('暂无可选项', output)
        self.assertNotIn('操作未完成', output)

    def test_ungranted_nodes_are_not_offered_for_binding(self):
        self.manager.add_inbound('not-allowed', 'hysteria2')
        output, _ = self.run_menu(['3', '5', '1', '0', '0', '0'])
        self.assertIn('REALITY', output)
        self.assertNotIn('not-allowed', output)

    def test_grant_only_offers_ungranted_nodes(self):
        other = self.manager.add_inbound('HY2', 'hysteria2')
        self.run_menu(['2', '5', '1', '1', '0', '0'])
        self.assertIn(other, self.store.read()['users'][self.user]['grants'])

    def test_add_node_uses_numbered_protocol_and_short_prompts(self):
        output, prompts = self.run_menu(['1', '2', '2', 'new-node', '', 'node.example', '', '0', '0'])
        node = next(node for node in self.store.read()['inbounds'].values() if node['name'] == 'new-node')
        self.assertEqual('hysteria2', node['protocol'])
        self.assertIn('选择协议', output)
        self.assertNotIn('输入上面对应的英文值', prompts)

    def test_edit_node_uses_selection_and_preserves_generated_path(self):
        websocket = self.manager.add_inbound('WS', 'cloudflare_ws')
        self.run_menu(['1', '3', '2', '1', '', 'node.example', 'node.example', '', '0', '0'])
        settings = self.store.read()['inbounds'][websocket]['settings']
        self.assertEqual(8443, settings['port'])
        self.assertEqual(443, settings['public_port'])
        self.assertEqual('cloudflare', settings['connection_mode'])
        self.assertTrue(settings['path'].startswith('/'))
        path = settings['path']
        self.run_menu(['1', '3', '2', '1', '', 'node.example', 'node.example', '', '0', '0'])
        self.assertEqual(path, self.store.read()['inbounds'][websocket]['settings']['path'])

    def test_add_user_all_is_atomic_and_preserves_isolation(self):
        self.run_menu(['2', '3', 'Bob', '0', '0'])
        users = self.store.read()['users']
        bob = next(user for user in users.values() if user['name'] == 'Bob')
        self.assertEqual({self.node}, set(bob['grants']))
        self.assertNotEqual(users[self.user]['grants'][self.node], bob['grants'][self.node])
        before = self.store.path.read_bytes()
        self.run_menu(['2', '3', 'Bob', '0', '0'])
        self.assertEqual(before, self.store.path.read_bytes())

    def test_add_user_all_without_nodes_does_not_create_user(self):
        empty = StateStore(Path(self.temp.name) / 'empty')
        manager = Manager(empty)
        with self.assertRaisesRegex(ValueError, '暂无节点'):
            manager.add_user_all('Bob')
        self.assertEqual({}, empty.read()['users'])

    def test_friendly_lists_hide_identifiers_and_secrets(self):
        self.add_proxy()
        output, _ = self.run_menu(['1', '1', '0', '2', '1', '0', '3', '1', '0', '0'])
        self.assertIn('Alice', output)
        self.assertIn('proxy.example.com:1080', output)
        self.assertNotIn(self.user, output)
        self.assertNotIn(self.node, output)
        self.assertNotIn('secret', output)
        self.assertNotIn('grants', output)

    def test_service_json_remains_available_and_redacted(self):
        self.add_proxy()
        output, _ = self.run_menu(['5', '5', '0', '0'])
        self.assertIn('"users":', output)
        self.assertIn(self.user, output)
        self.assertNotIn('secret', output)
        self.assertIn('***', output)

    def test_user_menu_rejects_removed_export_option(self):
        before = self.store.path.read_bytes()
        output, prompts = self.run_menu(['2', '9', '0', '0'])
        self.assertNotIn('导出客户端配置', output)
        self.assertNotIn('[客户端]', output)
        self.assertNotIn('保存到新目录', prompts)
        self.assertIn('编号无效', output)
        self.assertIn('请选择 [0-8]', prompts)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_remove_saved_egress_still_protects_active_binding(self):
        egress = self.add_proxy()
        self.manager.bind(self.user, self.node, egress)
        output, _ = self.run_menu(['3', '6', '1', '1', '1', '0', '0'])
        self.assertIn('出口正在使用', output)
        self.assertEqual(egress, self.store.read()['bindings'][f'{self.user}:{self.node}']['active'])

    def test_selecting_another_user_does_not_modify_first_user(self):
        second = self.manager.add_user('Bob')
        self.run_menu(['2', '4', '2', '2', '0', '0'])
        state = self.store.read()
        self.assertTrue(state['users'][self.user]['enabled'])
        self.assertFalse(state['users'][second]['enabled'])

    def test_revoke_and_delete_require_confirmation(self):
        egress = self.add_proxy()
        self.manager.bind(self.user, self.node, egress)
        self.run_menu(['2', '6', '1', '1', 'no', '0', '0'])
        self.assertIn(self.node, self.store.read()['users'][self.user]['grants'])
        self.run_menu(['2', '6', '1', '1', 'y', '0', '0'])
        self.assertEqual({}, self.store.read()['bindings'])
        self.assertEqual({}, self.store.read()['users'][self.user]['grants'])
        self.run_menu(['2', '8', '1', 'y', '0', '0'])
        self.assertEqual({}, self.store.read()['users'])

    def test_egress_creation_edit_test_and_deletion(self):
        self.run_menu(['3', '2', 'socks5://user:hidden@proxy.example.com:1080',
                       'proxy', '', '0', '0'])
        self.run_menu(['3', '3', '1', 'socks5://user:hidden@other.example.com:1081',
                       'updated', 'y', '0', '0'])
        profile = next(iter(self.store.read()['egress'].values()))
        self.assertEqual('updated', profile['name'])
        self.assertEqual('other.example.com', profile['settings']['server'])
        self.assertTrue(profile['settings']['udp'])
        with patch('sbmanager.cli.driver') as driver:
            driver.return_value.test_connection.return_value = {'note': '仅认证通过，未验证 UDP'}
            output, _ = self.run_menu(['3', '4', '1', '0', '0'])
            driver.return_value.test_connection.assert_called_once_with(profile)
        self.assertIn('未验证 UDP', output)
        self.run_menu(['3', '7', '1', 'y', '0', '0'])
        self.assertEqual({}, self.store.read()['egress'])

    def test_service_and_backup_actions_reach_existing_operations(self):
        deployment = Mock()
        deployment.service.active.return_value = True
        deployment.backups = Path(self.temp.name) / 'backups'
        deployment.backups.mkdir()
        (deployment.backups / 'old.json').touch()
        output, _ = self.run_menu(['5', '1', '2', '3', '0',
                                   '6', '1', '2', '3', '1', 'y', '4', '2', 'y', '0', '0'], deployment)
        deployment.service.logs.assert_called_once()
        deployment.backup.assert_called_once()
        deployment.restore.assert_called_once_with('old.json')
        deployment.prune.assert_called_once_with(2)
        self.assertTrue(self.store.read()['deployed'])
        self.assertEqual(2, self.store.read()['backup_keep'])
        self.assertIn('配置已生效，服务和端口检查通过', output)
        self.assertNotIn('请用客户端测试连接', output)

    def test_certificate_output_is_not_raw_json(self):
        result = {'domains': [{'domain': 'node.example', 'addresses': ['192.0.2.1']}],
                  'certificates': [{'file': 'node.crt', 'expires': 'Jan 1 2030'}]}
        with patch('sbmanager.cli.inspect', return_value=result):
            output, _ = self.run_menu(['5', '4', '0', '0'], Mock())
        self.assertIn('域名：node.example', output)
        self.assertIn('到期：Jan 1 2030', output)
        self.assertIn('检查范围：DNS、本地证书', output)
        self.assertNotIn('不代表签发或续期成功', output)
        self.assertNotIn('"domains"', output)

    def test_backup_retention_cancellation_does_not_prune(self):
        before = self.store.path.read_bytes()
        deployment = Mock()
        self.run_menu(['6', '4', '1', 'no', '0', '0'], deployment)
        deployment.prune.assert_not_called()
        self.assertEqual(before, self.store.path.read_bytes())


if __name__ == '__main__':
    unittest.main()
