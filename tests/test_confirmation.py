"""Verify explicit y/N confirmation without running system operations."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

from sbmanager.cli import confirm, edit_egress


class ConfirmationTests(unittest.TestCase):
    def test_confirmation_accepts_only_y_case_insensitively(self):
        for answer in ('y', 'Y', 'n', 'N', '', 'yes', 'invalid'):
            with self.subTest(answer=answer), patch('builtins.input', return_value=answer) as reader:
                self.assertEqual(answer.lower() == 'y', confirm('测试确认'))
                self.assertIn('[y/N]', reader.call_args.args[0])

    def test_udp_requires_explicit_y(self):
        for protocol, link in (('socks5', 'socks5://host:1080'),
                               ('ss', 'ss://aes-128-gcm:secret@host:8388')):
            for answer in ('y', 'Y', 'n', 'N', '', 'yes', 'invalid'):
                with self.subTest(protocol=protocol, answer=answer):
                    manager = Mock()
                    with patch('sbmanager.cli.getpass.getpass', return_value=link), \
                            patch('builtins.input', side_effect=['proxy', answer]) as reader:
                        edit_egress(manager)
                    self.assertEqual(answer.lower() == 'y', manager.save_egress.call_args.args[2]['udp'])
                    self.assertIn('[y/N]', reader.call_args.args[0])

    def test_installer_confirmation_guard(self):
        installer = (Path(__file__).resolve().parents[1] / 'install.sh').read_text()
        guard = next(line.strip() for line in installer.splitlines()
                     if '[[ "$answer" ==' in line)
        self.assertIn('[y/N]', installer)
        for answer in ('y', 'Y', 'n', 'N', '', 'yes', 'invalid'):
            with self.subTest(answer=answer):
                result = subprocess.run(
                    ['bash', '-c', 'answer=$1\n' + guard + '\nprintf accepted', 'confirmation', answer],
                    check=True, capture_output=True, text=True)
                self.assertEqual('accepted' if answer.lower() == 'y' else '', result.stdout)
