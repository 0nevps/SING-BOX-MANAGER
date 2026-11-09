"""Exercise BBR changes against fake procfs and a private sysctl directory."""
import contextlib
import io
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from sbmanager.cli import network_action, run
from sbmanager.core.transaction_manager import atomic_write
from sbmanager.security import ValidationError
from sbmanager.system import bbr


class BbrTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.proc = self.root / 'proc'
        self.config = self.root / 'sysctl.d' / '99-sbmanager-bbr.conf'
        for key, value in ((bbr.CONGESTION, 'cubic'), (bbr.QDISC, 'fq_codel'),
                           (bbr.AVAILABLE, 'reno cubic bbr')):
            self.write(key, value)
        for target, value in (('SYSCTL_ROOT', self.proc), ('CONFIG_PATH', self.config),
                              ('INSTALL_LOCK', self.root / 'bbr.lock')):
            patcher = patch.object(bbr, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        process = patch.object(bbr.subprocess, 'run', side_effect=self.execute)
        self.process = process.start()
        self.addCleanup(process.stop)
        modprobe = patch.object(bbr.shutil, 'which', return_value='/usr/sbin/modprobe')
        self.modprobe = modprobe.start()
        self.addCleanup(modprobe.stop)

    def write(self, key, value):
        path = self.proc.joinpath(*key.split('.'))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + '\n')

    def execute(self, command, **kwargs):
        if command[0] == 'sysctl':
            key, value = command[2].split('=', 1)
            self.write(key, value)
        return subprocess.CompletedProcess(command, 0)

    def assert_restored(self):
        self.assertEqual('cubic', bbr._read(bbr.CONGESTION))
        self.assertEqual('fq_codel', bbr._read(bbr.QDISC))

    def test_status_reads_live_default_without_commands_or_writes(self):
        self.assertFalse(bbr.enabled())
        self.write(bbr.CONGESTION, 'bbr')
        self.assertTrue(bbr.enabled())
        self.assertFalse(self.config.exists())
        self.process.assert_not_called()

    def test_enable_checks_live_settings_and_persists_private_file(self):
        bbr.enable()
        self.assertTrue(bbr.enabled())
        self.assertEqual('fq', bbr._read(bbr.QDISC))
        self.assertEqual(bbr.CONFIG, self.config.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(self.config.stat().st_mode))
        self.modprobe.assert_not_called()
        self.assertEqual([
            ['sysctl', '-w', 'net.core.default_qdisc=fq'],
            ['sysctl', '-w', 'net.ipv4.tcp_congestion_control=bbr'],
        ], [call.args[0] for call in self.process.call_args_list])
        for call in self.process.call_args_list:
            self.assertTrue(call.kwargs['check'])
            self.assertEqual(10, call.kwargs['timeout'])
        bbr.enable()
        self.assertEqual(bbr.CONFIG, self.config.read_bytes())

    def test_loads_module_only_when_bbr_is_not_available(self):
        self.write(bbr.AVAILABLE, 'reno cubic')

        def load(command, **kwargs):
            if command == ['/usr/sbin/modprobe', 'tcp_bbr']:
                self.write(bbr.AVAILABLE, 'reno cubic bbr')
            return self.execute(command, **kwargs)

        self.process.side_effect = load
        bbr.enable()
        self.assertTrue(bbr.enabled())
        self.assertEqual(['/usr/sbin/modprobe', 'tcp_bbr'], self.process.call_args_list[0].args[0])

    def test_unsupported_kernel_does_not_change_runtime_or_existing_file(self):
        self.write(bbr.AVAILABLE, 'reno cubic')
        atomic_write(self.config, b'# existing\n')
        for modprobe in ('/usr/sbin/modprobe', None):
            with self.subTest(modprobe=modprobe):
                self.modprobe.return_value = modprobe
                self.process.reset_mock()
                with self.assertRaisesRegex(ValidationError, '不支持 BBR'):
                    bbr.enable()
                self.assert_restored()
                self.assertEqual(b'# existing\n', self.config.read_bytes())
                self.assertFalse(any(call.args[0][0] == 'sysctl' for call in self.process.call_args_list))

    def test_partial_apply_failure_restores_original_settings_and_config(self):
        atomic_write(self.config, b'# original\n')
        self.config.chmod(0o640)

        def fail(command, **kwargs):
            if command[-1] == f'{bbr.CONGESTION}=bbr':
                raise subprocess.CalledProcessError(1, command)
            return self.execute(command, **kwargs)

        self.process.side_effect = fail
        with self.assertRaisesRegex(ValidationError, '已恢复'):
            bbr.enable()
        self.assert_restored()
        self.assertEqual(b'# original\n', self.config.read_bytes())
        self.assertEqual(0o640, stat.S_IMODE(self.config.stat().st_mode))

    def test_failed_persistence_removes_new_file_and_restores_runtime(self):
        def fail_after_replace(path, content):
            atomic_write(path, content)
            raise OSError('directory fsync failed')

        with patch.object(bbr, 'atomic_write', side_effect=fail_after_replace), \
                self.assertRaisesRegex(ValidationError, '已恢复'):
            bbr.enable()
        self.assert_restored()
        self.assertFalse(self.config.exists())

    def test_failed_persistence_restores_previous_file(self):
        atomic_write(self.config, b'# original\n')

        def fail_once(path, content):
            atomic_write(path, content)
            if content == bbr.CONFIG:
                raise OSError('directory fsync failed')

        with patch.object(bbr, 'atomic_write', side_effect=fail_once), \
                self.assertRaisesRegex(ValidationError, '已恢复'):
            bbr.enable()
        self.assert_restored()
        self.assertEqual(b'# original\n', self.config.read_bytes())

    def test_ignored_kernel_setting_does_not_report_success(self):
        self.process.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(command, 0)
        with self.assertRaisesRegex(ValidationError, '已恢复'):
            bbr.enable()
        self.assert_restored()
        self.assertFalse(self.config.exists())

    def test_rollback_failure_is_reported(self):
        self.process.side_effect = subprocess.TimeoutExpired('sysctl', 10)
        with self.assertRaisesRegex(ValidationError, '部分恢复未完成'):
            bbr.enable()
        self.assertFalse(self.config.exists())

    def test_symlink_is_rejected_before_system_changes(self):
        original = self.root / 'original.conf'
        original.write_text('# untouched\n')
        self.config.parent.mkdir()
        self.config.symlink_to(original)
        with self.assertRaisesRegex(ValidationError, '符号链接'):
            bbr.enable()
        self.assertEqual('# untouched\n', original.read_text())
        self.process.assert_not_called()

    def test_busy_lock_prevents_changes(self):
        with bbr.exclusive_lock(bbr.INSTALL_LOCK), \
                self.assertRaisesRegex(ValidationError, '另一个'):
            bbr.enable()
        self.process.assert_not_called()
        self.assertFalse(self.config.exists())


class BbrMenuTests(unittest.TestCase):
    def test_enable_requires_confirmation_and_does_not_restart_service(self):
        for answer in ('', 'n', 'no', 'y', 'Y'):
            with self.subTest(answer=answer), patch('builtins.input', return_value=answer) as reader, \
                    patch('sbmanager.cli.bbr.enable') as enable, \
                    patch('sbmanager.system.systemd.Systemd.restart') as restart, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                network_action(2, Mock())
                self.assertEqual(answer.lower() == 'y', enable.called)
                self.assertIn('/etc/sysctl.d/99-sbmanager-bbr.conf', reader.call_args.args[0])
                self.assertIn('全机 TCP', reader.call_args.args[0])
                restart.assert_not_called()
                self.assertEqual(answer.lower() == 'y', 'BBR 已开启' in output.getvalue())

    def test_enable_failure_has_no_success_message_and_menu_stays_usable(self):
        with patch('builtins.input', side_effect=['7', '2', 'y', '0', '0']), \
                patch('sbmanager.cli.bbr.enable', side_effect=ValidationError('内核不支持 BBR')), \
                patch('sbmanager.cli.bbr.enabled', return_value=False), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, run(Mock(), Mock(), Mock()))
        self.assertIn('操作未完成：内核不支持 BBR', output.getvalue())
        self.assertNotIn('BBR 已开启', output.getvalue())

    def test_top_status_refreshes_after_returning_to_main_menu(self):
        deployment = Mock()
        deployment.service.active.side_effect = [False, True]
        with patch('builtins.input', side_effect=['7', '2', 'y', '0', '0']), \
                patch('sbmanager.cli.bbr.enable') as enable, \
                patch('sbmanager.cli.bbr.enabled', side_effect=[False, True]) as enabled, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, run(Mock(), Mock(), deployment))
        text = output.getvalue()
        self.assertIn('BBR：未开启', text)
        self.assertIn('BBR：已开启', text)
        self.assertIn('sing-box 服务：未运行', text)
        self.assertIn('sing-box 服务：运行中', text)
        self.assertLess(text.index('BBR：未开启'), text.index('[业务配置]'))
        enable.assert_called_once_with()
        self.assertEqual(2, enabled.call_count)
        self.assertEqual(2, deployment.service.active.call_count)

    def test_status_failure_does_not_block_exit_or_imply_disabled(self):
        deployment = Mock()
        deployment.service.active.side_effect = subprocess.TimeoutExpired('systemctl', 10)
        with patch('builtins.input', return_value='0'), \
                patch('sbmanager.cli.bbr.enabled', side_effect=OSError('no procfs')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, run(Mock(), Mock(), deployment))
        self.assertIn('BBR：未知（读取失败）', output.getvalue())
        self.assertIn('sing-box 服务：未知（读取失败）', output.getvalue())
        self.assertNotIn('BBR：未开启', output.getvalue())

    def test_status_wraps_in_narrow_terminal(self):
        import os
        import unicodedata

        with patch('builtins.input', return_value='0'), \
                patch('sbmanager.cli.bbr.enabled', return_value=True), \
                patch('sbmanager.cli.shutil.get_terminal_size', return_value=os.terminal_size((24, 24))), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, run(Mock(), Mock(), Mock()))
        for line in output.getvalue().splitlines():
            width = sum(0 if unicodedata.combining(char) else
                        2 if unicodedata.east_asian_width(char) in 'WF' else 1 for char in line)
            self.assertLessEqual(width, 23)
