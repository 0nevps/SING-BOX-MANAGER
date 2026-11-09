"""Exercise maintenance without touching host services or installed files."""
import contextlib
import fcntl
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from sbmanager.cli import run
from sbmanager.security import ValidationError
from sbmanager.system import maintenance


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        for name, relative in (
                ('INSTALL_DIR', 'opt/sbmanager'), ('DATA_DIR', 'var/lib/sbmanager'),
                ('CONFIG_DIR', 'etc/sbmanager'), ('COMMAND', 'usr/local/bin/sbmanager'),
                ('UNIT', 'etc/systemd/system/sbmanager-sing-box.service'),
                ('DROP_INS', 'etc/systemd/system/sbmanager-sing-box.service.d'),
                ('INSTALL_LOCK', 'run/sbmanager-install.lock')):
            value = self.root / relative
            value.parent.mkdir(parents=True, exist_ok=True)
            self.stack.enter_context(patch.object(maintenance, name, value))
        for path in (maintenance.INSTALL_DIR, maintenance.DATA_DIR,
                     maintenance.CONFIG_DIR, maintenance.DROP_INS):
            path.mkdir()
            (path / 'managed-file').write_text('private')
        maintenance.COMMAND.write_text('wrapper')
        maintenance.UNIT.write_text('unit')
        self.calls = self.stack.enter_context(patch.object(maintenance.subprocess, 'run'))
        self.calls.return_value = subprocess.CompletedProcess([], 0, stdout='loaded\n')
        self.exec = self.stack.enter_context(patch.object(maintenance.os, 'execv'))

    def metadata(self, repository):
        build = maintenance.INSTALL_DIR / 'current'
        build.mkdir()
        (build / '.source-repository').write_text(repository)

    def test_update_uses_recorded_repository_and_restarts_fresh_menu(self):
        self.metadata('owner/project\n')
        maintenance.update()
        download, install = self.calls.call_args_list
        self.assertIn('https://raw.githubusercontent.com/owner/project/main/install.sh', download.args[0])
        self.assertEqual(['bash', download.args[0][-1], 'owner/project'], install.args[0])
        self.assertEqual('1', install.kwargs['env']['SBMANAGER_NO_MENU'])
        self.assertTrue(install.kwargs['check'])
        self.assertFalse(Path(download.args[0][-1]).exists())
        self.exec.assert_called_once_with(str(maintenance.COMMAND), [str(maintenance.COMMAND)])
        self.assertTrue((maintenance.DATA_DIR / 'managed-file').exists())

    def test_existing_install_without_metadata_uses_project_repository(self):
        maintenance.update()
        self.assertIn(f'https://raw.githubusercontent.com/{maintenance.DEFAULT_REPOSITORY}/main/install.sh',
                      self.calls.call_args_list[0].args[0])

    def test_invalid_repository_never_downloads_or_executes(self):
        self.metadata('owner/project/../../other')
        with self.assertRaises(ValidationError):
            maintenance.update()
        self.calls.assert_not_called()
        self.exec.assert_not_called()

    def test_download_or_install_failure_does_not_replace_running_menu(self):
        for failure in (0, 1):
            with self.subTest(failure=failure):
                self.calls.reset_mock()
                self.calls.side_effect = ([subprocess.CalledProcessError(1, 'curl')] if failure == 0
                                          else [None, subprocess.CalledProcessError(1, 'bash')])
                with self.assertRaises(subprocess.CalledProcessError):
                    maintenance.update()
                self.assertEqual(failure + 1, self.calls.call_count)
                self.exec.assert_not_called()
                self.assertTrue(maintenance.COMMAND.exists())
                self.assertTrue((maintenance.DATA_DIR / 'managed-file').exists())
                script = Path(self.calls.call_args_list[0].args[0][-1])
                self.assertFalse(script.parent.exists())

    def test_uninstall_removes_managed_paths_and_preserves_unrelated_files(self):
        unrelated = maintenance.UNIT.with_name('sing-box.service')
        unrelated.write_text('other software')
        outside = self.root / 'exported-client.json'
        outside.write_text('export')
        # Links inside managed directories must not delete outside content.
        (maintenance.DATA_DIR / 'external').symlink_to(outside)
        maintenance.uninstall()
        self.assertFalse(any(path.exists() for path in maintenance.uninstall_paths()))
        self.assertEqual('other software', unrelated.read_text())
        self.assertEqual('export', outside.read_text())
        commands = [call.args[0] for call in self.calls.call_args_list]
        self.assertEqual(['systemctl', 'disable', '--now', maintenance.Systemd.unit], commands[1])
        self.assertEqual(['systemctl', 'daemon-reload'], commands[2])
        self.assertTrue(maintenance.INSTALL_LOCK.exists())
        self.assertEqual(0o600, maintenance.INSTALL_LOCK.stat().st_mode & 0o777)

    def test_missing_unit_and_partial_install_can_be_removed(self):
        maintenance.UNIT.unlink()
        self.calls.return_value.stdout = 'not-found\n'
        maintenance.uninstall()
        maintenance.uninstall()
        self.assertFalse(any('disable' in call.args[0] for call in self.calls.call_args_list))
        self.assertFalse(maintenance.COMMAND.exists())

    def test_service_stop_failure_keeps_all_files(self):
        self.calls.side_effect = [subprocess.CompletedProcess([], 0, stdout='loaded\n'),
                                 subprocess.CalledProcessError(1, 'systemctl')]
        with self.assertRaises(subprocess.CalledProcessError):
            maintenance.uninstall()
        self.assertTrue(all(path.exists() for path in maintenance.uninstall_paths()))

    def test_reload_failure_keeps_data_and_command(self):
        self.calls.side_effect = [subprocess.CompletedProcess([], 0, stdout='loaded\n'), None,
                                 subprocess.CalledProcessError(1, 'systemctl')]
        with self.assertRaises(subprocess.CalledProcessError):
            maintenance.uninstall()
        self.assertTrue(maintenance.DATA_DIR.exists())
        self.assertTrue(maintenance.COMMAND.exists())

    def test_busy_installer_or_data_lock_prevents_uninstall(self):
        for path in (maintenance.INSTALL_LOCK, maintenance.DATA_DIR / 'state.lock'):
            with self.subTest(path=path), path.open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(ValidationError):
                    maintenance.uninstall()
                self.calls.assert_not_called()
                self.assertTrue(maintenance.COMMAND.exists())

    def test_data_directory_symlink_is_rejected_before_service_changes(self):
        actual = maintenance.DATA_DIR.with_name('other-data')
        maintenance.DATA_DIR.rename(actual)
        maintenance.DATA_DIR.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(ValidationError):
            maintenance.uninstall()
        self.calls.assert_not_called()
        self.assertTrue((actual / 'managed-file').exists())

    def test_redirected_parent_directory_is_rejected(self):
        parent = maintenance.UNIT.parent
        actual = parent.with_name('other-system')
        parent.rename(actual)
        parent.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(ValidationError):
            maintenance.uninstall()
        self.calls.assert_not_called()
        self.assertTrue(maintenance.COMMAND.exists())

    def test_nested_mount_point_is_rejected_before_deletion(self):
        mounted = maintenance.DATA_DIR / 'mounted'
        mounted.mkdir()
        with patch.object(Path, 'is_mount', autospec=True,
                          side_effect=lambda path: path == mounted):
            with self.assertRaises(ValidationError):
                maintenance.uninstall()
        self.calls.assert_not_called()
        self.assertTrue(maintenance.COMMAND.exists())

    def test_data_removal_failure_keeps_command_and_builds_for_retry(self):
        original = maintenance._remove
        def fail_on_data(path):
            if path == maintenance.DATA_DIR:
                raise PermissionError('cannot remove data')
            original(path)
        with patch.object(maintenance, '_remove', side_effect=fail_on_data):
            with self.assertRaises(PermissionError):
                maintenance.uninstall()
        self.assertTrue(maintenance.COMMAND.exists())
        self.assertTrue(maintenance.INSTALL_DIR.exists())
        self.assertTrue(maintenance.DATA_DIR.exists())

    def test_command_symlink_is_removed_without_following_target(self):
        outside = self.root / 'other-command'
        outside.write_text('unrelated')
        maintenance.COMMAND.unlink()
        maintenance.COMMAND.symlink_to(outside)
        maintenance.uninstall()
        self.assertEqual('unrelated', outside.read_text())
        self.assertFalse(maintenance.COMMAND.is_symlink())


class MaintenanceMenuTests(unittest.TestCase):
    def menu(self, answers):
        output = io.StringIO()
        with patch('builtins.input', side_effect=answers) as reader, contextlib.redirect_stdout(output):
            self.assertEqual(0, run(Mock(), Mock(), Mock()))
        return output.getvalue(), '\n'.join(call.args[0] for call in reader.call_args_list)

    def test_update_menu_calls_installer_bridge(self):
        with patch.object(maintenance, 'update') as update:
            output, _ = self.menu(['8', '1', '0', '0'])
        update.assert_called_once_with()
        self.assertIn('更新管理程序', output)

    def test_uninstall_cancel_does_not_remove_files(self):
        with patch.object(maintenance, 'uninstall') as uninstall:
            _, prompts = self.menu(['8', '3', 'no', '0', '0'])
        uninstall.assert_not_called()
        for path in maintenance.uninstall_paths():
            self.assertIn(str(path), prompts)
        self.assertIn('永久删除', prompts)
        self.assertIn('无法撤销', prompts)

    def test_uninstall_success_exits_without_reopening_menu(self):
        with patch.object(maintenance, 'uninstall') as uninstall:
            output, _ = self.menu(['8', '3', 'y'])
        uninstall.assert_called_once_with()
        self.assertIn('已卸载', output)
        self.assertEqual(1, output.count('主菜单'))

    def test_uninstall_failure_is_not_reported_as_success(self):
        with patch.object(maintenance, 'uninstall', side_effect=OSError('stop failed')):
            output, _ = self.menu(['8', '3', 'y', '0', '0'])
        self.assertIn('操作未完成', output)
        self.assertNotIn('已卸载', output)
