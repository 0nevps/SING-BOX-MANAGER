"""Verify menu layout and optional terminal colors without service changes."""
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
        manager.add_user.return_value = 'user-id'
        with patch.dict(os.environ, environment or {'TERM': 'xterm-256color'}, clear=True), \
                patch('builtins.input', side_effect=answers) as reader, \
                contextlib.redirect_stdout(output):
            self.assertEqual(0, run(manager))
        prompts = '\n'.join(call.args[0] for call in reader.call_args_list)
        return output.getvalue(), prompts

    def test_each_option_has_its_own_line_and_keeps_its_number(self):
        output, _ = self.run_menu(['0'])
        options = re.findall(r'^\s+(\d+)\s+(.+)$', output, re.MULTILINE)
        self.assertEqual(set(range(28)), {int(number) for number, _ in options})
        self.assertEqual(28, len(options))
        self.assertIn(' 14 检查配置并启动服务', output)
        self.assertIn(' 27 升级 sing-box', output)

    def test_sections_and_guidance_have_spacing(self):
        output, _ = self.run_menu(['0'])
        for title in ('常用操作', '用户与权限', '节点管理', '出口管理', '服务与证书', '备份管理'):
            self.assertIn(f'\n\n{title}\n', output)
        self.assertIn('节点是手机或电脑连接的入口；\n', output)
        self.assertIn('需要填写 ID 时，先选 1，复制对应的 id。\n', output)
        self.assertIn('\n\n  0 退出\n\n', output)

    def test_redirected_output_has_no_color_codes(self):
        output, prompts = self.run_menu(['0'])
        self.assertNotIn('\x1b[', output + prompts)

    def test_terminal_uses_semantic_colors(self):
        output, prompts = self.run_menu(['0'], TerminalOutput())
        self.assertIn('\x1b[1;36mSING-BOX MANAGER\x1b[0m', output)
        self.assertIn('\x1b[36m 14\x1b[0m 检查配置并启动服务', output)
        self.assertIn('\x1b[31m  9 删除用户\x1b[0m', output)
        self.assertIn('\x1b[33m本地测试模式', output)
        self.assertIn('\x1b[36m', prompts)

    def test_no_color_and_dumb_terminal_disable_colors(self):
        for environment in ({'NO_COLOR': '', 'TERM': 'xterm'}, {'TERM': 'dumb'}):
            with self.subTest(environment=environment):
                output, prompts = self.run_menu(['0'], TerminalOutput(), environment)
                self.assertNotIn('\x1b[', output + prompts)

    def test_error_and_success_feedback_are_distinct(self):
        output, _ = self.run_menu(['99', '2', 'Alice', '0'], TerminalOutput())
        self.assertIn('\x1b[33m没有这个菜单选项', output)
        self.assertIn('\x1b[32m已添加用户，用户 ID: user-id\x1b[0m', output)
        output, _ = self.run_menu(['14', '0'], TerminalOutput())
        self.assertIn('\x1b[31m操作未完成', output)

    def test_input_starts_on_its_own_line_and_strips_whitespace(self):
        with patch('builtins.input', return_value='  value  ') as reader, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual('value', ask('用户名'))
        reader.assert_called_once_with('用户名\n> ')


if __name__ == '__main__':
    unittest.main()
