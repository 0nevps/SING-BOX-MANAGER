from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


class InstallerMenuTests(unittest.TestCase):
    def setUp(self):
        self.source = (Path(__file__).resolve().parents[1] / 'install.sh').read_text()
        start = self.source.index('open_menu() {')
        end = self.source.index('\ndownload_source() {', start)
        self.function = self.source[start:end]

    def test_menu_uses_terminal_and_releases_installation_locks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = root / 'terminal'
            terminal.touch()
            menu = root / 'menu'
            menu.write_text(
                '#!/bin/bash\n'
                'if [[ -e /dev/fd/8 || -e /dev/fd/9 ]]; then exit 20; fi\n'
                'printf "menu opened\\n"\n')
            menu.chmod(0o700)
            function = self.function.replace('/usr/local/bin/sbmanager', shlex.quote(str(menu)))
            function = function.replace('/dev/tty', shlex.quote(str(terminal)))
            result = subprocess.run(
                ['bash', '-c', function + '\nexec 8>"$1" 9>"$2"\nopen_menu',
                 'test', str(root / 'state.lock'), str(root / 'install.lock')],
                input='', capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn('menu opened', terminal.read_text())

    def test_without_terminal_prints_manual_command(self):
        with tempfile.TemporaryDirectory() as directory:
            function = self.function.replace('/dev/tty', str(Path(directory) / 'missing' / 'tty'))
            function = function.replace('/usr/local/bin/sbmanager', 'false')
            result = subprocess.run(['bash', '-c', function + '\nopen_menu'],
                                    input='', capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('运行 sudo sbmanager 打开菜单。\n', result.stdout)

    def test_installed_command_uses_service_entrypoint(self):
        wrapper = self.source.split("<<'WRAPPER'\n", 1)[1].split('\nWRAPPER', 1)[0]
        self.assertEqual(
            '#!/bin/sh\n'
            'exec python3 /opt/sbmanager/current/main.py '
            '--sing-box /opt/sbmanager/current/sing-box "$@"', wrapper)

    def test_first_and_repeat_install_open_menu_after_success(self):
        self.assertNotIn('无需重复安装', self.source)
        self.assertNotIn('程序安装完成，即将打开管理菜单', self.source)
        completion = self.source[self.source.index('rollback_ready=0\n'):]
        self.assertTrue(completion.endswith('\nopen_menu\n'))
