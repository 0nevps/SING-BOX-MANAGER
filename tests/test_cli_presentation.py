"""Verify concise menus, navigation, and optional terminal colors."""
import contextlib
import io
import os
import re
import unittest
from unittest.mock import Mock, mock_open, patch

from sbmanager.cli import Cancelled, MENUS, ask, choose, main_status, run


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
        options = re.findall(r'^ +(\d+)\) (.+)$', output, re.MULTILINE)
        self.assertEqual([str(number) for number in (1, 2, 3, 4, 5, 6, 7, 8, 0)],
                         [number for number, _ in options])
        self.assertEqual(['节点管理', '用户管理', '出口管理', '端口转发', '服务管理',
                          '备份与恢复', '网络设置', '更新与卸载', '退出'],
                         [label for _, label in options])
        for text in ('复制', 'ID', 'SOCKS5', '删除用户', 'users 是用户'):
            self.assertNotIn(text, output)
        self.assertLessEqual(len(output.splitlines()), 36)
        self.assertRegex(output, r'(?m)^ +SING-BOX MANAGER · 主菜单$')
        self.assertLess(output.index('主机名：'), output.index('请选择操作：'))
        self.assertLess(output.index('sing-box 服务：'), output.index('[业务配置]'))
        self.assertEqual(['业务配置', '运行与维护', '系统设置'],
                         re.findall(r'^  \[(.+)\]$', output, re.MULTILINE))

    def test_menu_rules_are_short_on_wide_terminals(self):
        with patch('sbmanager.cli.shutil.get_terminal_size', return_value=os.terminal_size((120, 24))):
            output, _ = self.run_menu(['2', '0', '0'])
        rules = re.findall(r'^[=-]+$', output, re.MULTILINE)
        self.assertTrue(rules)
        self.assertTrue(all(len(rule) == 56 for rule in rules))
        title = next(line for line in output.splitlines() if 'SING-BOX MANAGER' in line)
        self.assertEqual(15, len(title) - len(title.lstrip()))

    def test_submenu_returns_to_main(self):
        output, _ = self.run_menu(['2', '0', '0'])
        self.assertEqual(2, output.count('主菜单'))
        self.assertRegex(output, r'(?m)^ +用户管理$')
        self.assertIn('\n   0) 返回\n', output)
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
        self.assertIn('\x1b[1;32mSING-BOX MANAGER · 主菜单\x1b[0m', output)
        self.assertIn('\x1b[32m' + '=' * 56 + '\x1b[0m', output)
        self.assertIn('\x1b[34m   1) \x1b[0m\x1b[32m节点管理\x1b[0m', output)
        self.assertIn('\x1b[31m删除用户\x1b[0m', output)
        self.assertIn('\x1b[33m取消节点权限\x1b[0m', output)
        self.assertNotIn('[危险]', output)
        self.assertNotIn('[注意]', output)
        self.assertIn('\x1b[33m   0) \x1b[0m', output)
        self.assertIn('\x1b[32m  请输入选项 [0-8]: \x1b[0m', prompts)

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

    def test_all_menus_omit_risk_suffixes_without_color(self):
        answers = [answer for section in range(1, len(MENUS) + 1)
                   for answer in (str(section), '0')] + ['0']
        output, prompts = self.run_menu(answers)
        self.assertNotIn('[危险]', output)
        self.assertNotIn('[注意]', output)
        self.assertNotIn('\x1b[', output)
        for _, labels in MENUS:
            for label in labels:
                with self.subTest(label=label):
                    self.assertRegex(output, rf'(?m)^ +\d+\) {re.escape(label)}$')
        self.assertIn('请输入选项 [0-8]: ', prompts)

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

    def test_host_information_is_read_only_and_has_semantic_colors(self):
        deployment = Mock()
        deployment.service.active.return_value = False
        output = TerminalOutput()
        with patch.dict(os.environ, {'TERM': 'xterm'}, clear=True), \
                patch('sbmanager.cli.platform.node', return_value='vps-example'), \
                patch('sbmanager.cli.platform.release', return_value='6.1.0-amd64'), \
                patch('sbmanager.cli.platform.freedesktop_os_release', create=True,
                      return_value={'PRETTY_NAME': 'Debian GNU/Linux 12'}), \
                patch('sbmanager.cli.bbr.enabled', return_value=True), \
                contextlib.redirect_stdout(output):
            main_status(deployment)
        text = output.getvalue()
        self.assertIn('\x1b[32m  主机名：\x1b[0m\x1b[34mvps-example\x1b[0m', text)
        self.assertIn('\x1b[34m6.1.0-amd64\x1b[0m', text)
        self.assertIn('\x1b[34mDebian GNU/Linux 12\x1b[0m', text)
        self.assertIn('\x1b[31m未运行\x1b[0m', text)
        self.assertIn('\x1b[32m已开启\x1b[0m', text)
        deployment.service.restart.assert_not_called()

    def test_host_information_failure_does_not_block_menu(self):
        with patch('sbmanager.cli.platform.node', side_effect=OSError('unavailable')), \
                patch('sbmanager.cli.platform.release', return_value=''), \
                patch('sbmanager.cli.platform.freedesktop_os_release', create=True,
                      side_effect=OSError('missing')):
            output, _ = self.run_menu(['0'])
        self.assertIn('主机名：未知（读取失败）', output)
        self.assertIn('系统：未知', output)
        self.assertIn('发行版：未知（读取失败）', output)
        self.assertIn('0) 退出', output)
        self.assertNotIn('操作未完成', output)

    def test_python39_reads_distribution_without_platform_api(self):
        for value in ('"Debian GNU/Linux 11 (bullseye)"',
                      "'Debian GNU/Linux 11 (bullseye)'", 'Debian'):
            with self.subTest(value=value), \
                    patch('sbmanager.cli.platform', spec=['node', 'release']), \
                    patch('builtins.open', mock_open(read_data=(
                        '# distribution metadata\nNAME=Debian\nPRETTY_NAME=' + value + '\n'))) as source:
                output, _ = self.run_menu(['0'])
                self.assertIn('发行版：' + value.strip('\'"'), output)
                self.assertIn('0) 退出', output)
                source.assert_called_once_with('/etc/os-release', encoding='utf-8')

    def test_python39_falls_back_to_vendor_os_release(self):
        source = mock_open(read_data='PRETTY_NAME="Debian GNU/Linux 11"\n')
        source.side_effect = [FileNotFoundError('missing'), source.return_value]
        with patch('sbmanager.cli.platform', spec=['node', 'release']), \
                patch('builtins.open', source):
            output, _ = self.run_menu(['0'])
        self.assertIn('发行版：Debian GNU/Linux 11', output)
        self.assertEqual(['/etc/os-release', '/usr/lib/os-release'],
                         [call.args[0] for call in source.call_args_list])

    def test_python39_distribution_read_failure_does_not_block_menu(self):
        for error in (FileNotFoundError('missing'), PermissionError('denied')):
            with self.subTest(error=error), \
                    patch('sbmanager.cli.platform', spec=['node', 'release']), \
                    patch('builtins.open', side_effect=error):
                output, _ = self.run_menu(['0'])
                self.assertIn('发行版：未知（读取失败）', output)
                self.assertIn('0) 退出', output)

    def test_python39_missing_or_invalid_distribution_name_does_not_block_menu(self):
        for content, expected in (('NAME=Debian\n', '未知'),
                                  ('PRETTY_NAME=""\n', '未知'),
                                  ('PRETTY_NAME="unterminated\n', '未知（读取失败）')):
            with self.subTest(content=content), \
                    patch('sbmanager.cli.platform', spec=['node', 'release']), \
                    patch('builtins.open', mock_open(read_data=content)):
                output, _ = self.run_menu(['0'])
                self.assertIn('发行版：' + expected, output)
                self.assertIn('0) 退出', output)

    def test_narrow_main_menu_wraps_host_information_and_title(self):
        import unicodedata

        with patch('sbmanager.cli.shutil.get_terminal_size', return_value=os.terminal_size((24, 24))), \
                patch('sbmanager.cli.platform.node', return_value='vps-' + 'long-name-' * 8), \
                patch('sbmanager.cli.platform.freedesktop_os_release', create=True,
                      return_value={'PRETTY_NAME': 'Debian GNU/Linux 12 (bookworm)'}):
            output, _ = self.run_menu(['0'])
        for line in output.splitlines():
            width = sum(0 if unicodedata.combining(char) else
                        2 if unicodedata.east_asian_width(char) in 'WF' else 1 for char in line)
            self.assertLessEqual(width, 23)
        compact = ''.join(output.split())
        self.assertIn('SING-BOXMANAGER·主菜单', compact)
        self.assertIn('vps-' + 'long-name-' * 8, compact)

    def test_menu_prompt_is_inline_and_accepts_whitespace(self):
        with patch('builtins.input', return_value='  1  ') as reader, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual('value', choose('选择节点', [('value', '示例节点')]))
        reader.assert_called_once_with('  请输入选项 [0-1]: ')

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
