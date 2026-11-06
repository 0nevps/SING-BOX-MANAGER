"""Keep beginner-facing guidance accurate without changing menu behavior."""
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
        output = io.StringIO()
        with patch('builtins.input', side_effect=answers) as ask, contextlib.redirect_stdout(output):
            result = run(self.manager, Mock(), deployment)
        self.assertEqual(0, result)
        prompts = '\n'.join(call.args[0] for call in ask.call_args_list)
        return output.getvalue(), prompts

    def test_menu_explains_terms_and_id_source(self):
        output, prompts = self.run_menu(['0'])
        for text in ('本地测试模式', '节点是手机或电脑连接的入口', '出口是 VPS 访问网络时使用的线路',
                     'users 是用户，inbounds 是节点，egress 是出口', '14 检查配置并启动服务',
                     '11 重置连接密钥', '27 升级 sing-box'):
            self.assertIn(text, output)
        self.assertIn('请输入菜单编号', prompts)

    def test_unsupported_local_action_explains_where_to_run_it(self):
        before = self.store.path.read_bytes()
        output, _ = self.run_menu(['14', '0'])
        self.assertIn('本地模式不能启动服务', output)
        self.assertIn('sudo sbmanager', output)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_delete_cancellation_warns_and_preserves_data(self):
        before = self.store.path.read_bytes()
        _, prompts = self.run_menu(['9', self.user, 'no', '0'])
        self.assertIn('删除后无法直接撤销', prompts)
        self.assertIn('全部节点权限和出口设置', prompts)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_reset_warns_that_old_client_configuration_expires(self):
        before = self.store.read()['users'][self.user]['grants'][self.node]
        _, prompts = self.run_menu(['11', self.user, self.node, '0'])
        self.assertIn('旧连接密钥失效', prompts)
        self.assertIn('需重新导出客户端配置', prompts)
        self.assertNotEqual(before, self.store.read()['users'][self.user]['grants'][self.node])

    def test_empty_egress_still_selects_direct_and_keeps_saved_egress(self):
        egress = self.manager.save_egress('proxy', 'socks5', {
            'server': 'proxy.example.com', 'port': 1080,
            'username': 'alice', 'password': 'secret', 'udp': False})
        self.manager.bind(self.user, self.node, egress)
        _, prompts = self.run_menu(['6', self.user, self.node, '', '0'])
        self.assertIn('直接回车使用直连 DIRECT，不经过代理出口', prompts)
        binding = self.store.read()['bindings'][f'{self.user}:{self.node}']
        self.assertIsNone(binding['active'])
        self.assertEqual([egress], binding['saved'])

    def test_restore_cancellation_warns_and_does_not_restore(self):
        deployment = Mock()
        _, prompts = self.run_menu(['23', 'backup.json', 'no', '0'], deployment)
        self.assertIn('替换当前用户、节点、出口和配置，并重启服务', prompts)
        self.assertIn('当前设置会另存备份', prompts)
        deployment.restore.assert_not_called()

    def test_upgrade_cancellation_warns_and_does_not_upgrade(self):
        with patch('sbmanager.system.kernel.upgrade') as upgrade:
            _, prompts = self.run_menu(['27', '1.14.4', 'no', '0'], Mock())
        self.assertIn('连接可能短暂中断', prompts)
        self.assertIn('不要加 v', prompts)
        upgrade.assert_not_called()

    def test_invalid_enable_choice_gives_exact_accepted_values(self):
        before = self.store.path.read_bytes()
        output, prompts = self.run_menu(['7', self.user, 'yes', '0'])
        self.assertIn('停用后不能连接，原设置保留', prompts)
        self.assertIn('请输入 enable（启用）或 disable（停用）', output)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_duplicate_username_explains_how_to_continue(self):
        before = self.store.path.read_bytes()
        output, _ = self.run_menu(['2', 'Alice', '0'])
        self.assertIn('这个用户名已存在，请换一个名称', output)
        self.assertEqual(before, self.store.path.read_bytes())


if __name__ == '__main__':
    unittest.main()
