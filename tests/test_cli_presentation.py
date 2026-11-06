"""Verify concise menus, navigation, and optional terminal colors."""
import contextlib
import io
import os
import re
import unittest
from unittest.mock import Mock, patch

from sbmanager.cli import ask, run


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
            self.assertEqual(0, run(manager))
        return output.getvalue(), '\n'.join(call.args[0] for call in reader.call_args_list)

    def test_main_menu_has_only_six_categories_and_exit(self):
        output, _ = self.run_menu(['0'])
        options = re.findall(r'^ +(\d+) (.+)$', output, re.MULTILINE)
        self.assertEqual([str(number) for number in (1, 2, 3, 4, 5, 6, 0)],
                         [number for number, _ in options])
        for title in ('节点管理', '用户管理', '出口管理', '服务管理', '备份与恢复', '高级与帮助'):
            self.assertIn(title, output)
        for text in ('复制', 'ID', 'SOCKS5', '删除用户', 'users 是用户'):
            self.assertNotIn(text, output)
        self.assertLessEqual(len(output.splitlines()), 14)

    def test_submenu_returns_to_main(self):
        output, _ = self.run_menu(['2', '0', '0'])
        self.assertEqual(2, output.count('主菜单'))
        self.assertIn('\n\n用户管理\n', output)
        self.assertIn('\n 0 返回\n', output)
        self.assertIn('删除用户', output)
        self.assertNotIn('删除出口', output)

    def test_redirected_output_has_no_color_codes(self):
        output, prompts = self.run_menu(['0'])
        self.assertNotIn('\x1b[', output + prompts)

    def test_terminal_uses_semantic_colors(self):
        output, prompts = self.run_menu(['2', '0', '0'], TerminalOutput())
        self.assertIn('\x1b[1;36mSING-BOX MANAGER\x1b[0m', output)
        self.assertIn('\x1b[36m 1\x1b[0m 节点管理', output)
        self.assertIn('\x1b[31m 8 删除用户\x1b[0m', output)
        self.assertIn('\x1b[33m本地测试模式', output)
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

    def test_input_starts_on_its_own_line_and_strips_whitespace(self):
        with patch('builtins.input', return_value='  value  ') as reader, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual('value', ask('用户名'))
        reader.assert_called_once_with('用户名\n> ')

    def test_keyboard_interrupt_and_eof_exit_cleanly(self):
        for error in (KeyboardInterrupt, EOFError):
            with self.subTest(error=error), patch('builtins.input', side_effect=error), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, run(Mock()))


if __name__ == '__main__':
    unittest.main()
