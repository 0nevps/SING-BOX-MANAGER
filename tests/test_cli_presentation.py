"""Verify concise menus, navigation, and optional terminal colors."""
import contextlib
import io
import os
import re
import unittest
from unittest.mock import Mock, patch

from sbmanager.cli import Cancelled, MENUS, ask, choose, run


class TerminalOutput(io.StringIO):
    def isatty(self):
        return True


class CliPresentationTests(unittest.TestCase):
    def run_menu(self, answers, output=None, environment=None):
        output = output if output is not None else io.StringIO()
        manager = Mock()
        with patch.dict(os.environ, environment or {'TERM': 'xterm-256color'}, clear=True), \
                patch('builtins.input', side_effect=answers) as reader, \
                contextlib.redirect_stdout(output):
            self.assertEqual(0, run(manager, Mock(), Mock()))
        return output.getvalue(), '\n'.join(call.args[0] for call in reader.call_args_list)

    def test_main_menu_has_eight_categories_and_exit(self):
        output, _ = self.run_menu(['0'])
        options = re.findall(r'^ +(\d+) (.+)$', output, re.MULTILINE)
        self.assertEqual([str(number) for number in (1, 2, 3, 4, 5, 6, 7, 8, 0)],
                         [number for number, _ in options])
        self.assertEqual(['节点管理', '用户管理', '出口管理', '端口转发', '服务管理',
                          '备份与恢复', '网络设置', '更新与卸载', '退出'],
                         [label for _, label in options])
        for text in ('复制', 'ID', 'SOCKS5', '删除用户', 'users 是用户'):
            self.assertNotIn(text, output)
        self.assertLessEqual(len(output.splitlines()), 22)
        self.assertIn('  SING-BOX MANAGER\n  主菜单\n', output)
        self.assertEqual(['业务配置', '运行与维护', '系统设置'],
                         re.findall(r'^  \[(.+)\]$', output, re.MULTILINE))

    def test_menu_rules_are_short_on_wide_terminals(self):
        with patch('sbmanager.cli.shutil.get_terminal_size', return_value=os.terminal_size((120, 24))):
            output, _ = self.run_menu(['2', '0', '0'])
        rules = re.findall(r'^[=-]+$', output, re.MULTILINE)
        self.assertTrue(rules)
        self.assertTrue(all(len(rule) == 32 for rule in rules))

    def test_submenu_returns_to_main(self):
        output, _ = self.run_menu(['2', '0', '0'])
        self.assertEqual(2, output.count('主菜单'))
        self.assertIn('\n  用户管理\n', output)
        self.assertIn('\n  0 返回\n', output)
        self.assertIn('删除用户', output)
        self.assertNotIn('删除出口', output)

    def test_submenus_are_flat_and_network_labels_are_concise(self):
        for title, labels in MENUS:
            with self.subTest(title=title), patch('builtins.input', return_value='0'), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(Cancelled):
                    choose(title, enumerate(labels, 1), back='返回')
                self.assertNotRegex(output.getvalue(), r'(?m)^  \[.+\]$')
        self.assertEqual(('节点流量仅用 IPv4', '开启 BBR'), MENUS[6][1])

    def test_every_menu_number_dispatches_to_its_matching_action(self):
        handlers = ('node_action', 'user_action', 'egress_action', 'forward_action',
                    'service_action', 'backup_action', 'network_action', 'maintenance_action')
        for section, (_, labels) in enumerate(MENUS, 1):
            for action in range(1, len(labels) + 1):
                with self.subTest(section=section, action=action), contextlib.ExitStack() as stack:
                    mocks = [stack.enter_context(patch('sbmanager.cli.' + name, return_value=None))
                             for name in handlers]
                    manager, engine, deployment = Mock(), Mock(), Mock()
                    stack.enter_context(patch('builtins.input',
                                              side_effect=[str(section), str(action), '0', '0']))
                    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    self.assertEqual(0, run(manager, engine, deployment))
                    for index, handler in enumerate(mocks, 1):
                        if index != section:
                            handler.assert_not_called()
                        elif section == 1:
                            handler.assert_called_once_with(action, manager, engine)
                        elif section in (5, 6, 8):
                            handler.assert_called_once_with(action, manager, deployment)
                        else:
                            handler.assert_called_once_with(action, manager)

    def test_redirected_output_has_no_color_codes(self):
        output, prompts = self.run_menu(['0'])
        self.assertNotIn('\x1b[', output + prompts)

    def test_terminal_uses_semantic_colors(self):
        output, prompts = self.run_menu(['2', '0', '0'], TerminalOutput())
        self.assertIn('\x1b[1;36m  SING-BOX MANAGER\x1b[0m', output)
        self.assertIn('\x1b[36m  1 节点管理\x1b[0m', output)
        self.assertIn('\x1b[31m  8 删除用户 [危险]\x1b[0m', output)
        self.assertIn('\x1b[36m', prompts)

    def test_no_color_and_dumb_terminal_disable_colors(self):
        for environment in ({'NO_COLOR': '', 'TERM': 'xterm'}, {'TERM': 'dumb'}):
            with self.subTest(environment=environment):
                output, prompts = self.run_menu(['0'], TerminalOutput(), environment)
                self.assertNotIn('\x1b[', output + prompts)

    def test_invalid_choice_retries_without_leaving_menu(self):
        output, _ = self.run_menu(['99', '2', '2', 'Alice', '0', '0'], TerminalOutput())
        self.assertIn('\x1b[33m编号无效', output)
        self.assertIn('\x1b[32m用户已添加\x1b[0m', output)
        self.assertNotIn('本次操作已结束', output)

    def test_danger_is_visible_without_color(self):
        output, prompts = self.run_menu(['8', '0', '7', '0', '0'])
        self.assertIn('卸载全部 [危险]', output)
        self.assertIn('更新管理程序 [注意]', output)
        self.assertIn('开启 BBR [注意]', output)
        self.assertIn('请选择 [0-8]', prompts)

    def test_narrow_menu_wraps_chinese_without_losing_labels(self):
        import unicodedata

        output = io.StringIO()
        label = '很长的节点名称 · VLESS + REALITY + Vision · example.com:443'
        with patch('sbmanager.cli.shutil.get_terminal_size', return_value=os.terminal_size((24, 24))), \
                patch('builtins.input', return_value='1'), contextlib.redirect_stdout(output):
            self.assertEqual('node', choose('选择节点', [('node', label)]))
        for line in output.getvalue().splitlines():
            cells = sum(0 if unicodedata.combining(char) else
                        2 if unicodedata.east_asian_width(char) in 'WF' else 1 for char in line)
            self.assertLessEqual(cells, 23)
        self.assertIn(''.join(label.split()), ''.join(output.getvalue().split()))

    def test_only_main_menu_queries_live_status_without_reading_state(self):
        manager, deployment = Mock(), Mock()
        with patch('builtins.input', side_effect=['5', '0', '0']), \
                patch('sbmanager.cli.bbr.enabled', return_value=False) as enabled, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, run(manager, Mock(), deployment))
        manager.store.read.assert_not_called()
        self.assertEqual(2, deployment.service.active.call_count)
        self.assertEqual(2, enabled.call_count)
        deployment.service.restart.assert_not_called()

    def test_input_starts_on_its_own_line_and_strips_whitespace(self):
        with patch('builtins.input', return_value='  value  ') as reader, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual('value', ask('用户名'))
        reader.assert_called_once_with('用户名\n> ')

    def test_keyboard_interrupt_and_eof_exit_cleanly(self):
        for error in (KeyboardInterrupt, EOFError):
            with self.subTest(error=error), patch('builtins.input', side_effect=error), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, run(Mock(), Mock(), Mock()))


if __name__ == '__main__':
    unittest.main()
