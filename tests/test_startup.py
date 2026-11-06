import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sbmanager.app import main
from sbmanager.core.state_manager import StateStore
from sbmanager.modules.manager import Manager


class StartupTests(unittest.TestCase):
    def test_node_menu_rejects_removed_option_without_changing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(directory)
            output = io.StringIO()
            with patch('sys.argv', ['sbmanager']), \
                 patch('sbmanager.app.platform.system', return_value='Linux'), \
                 patch('sbmanager.app.os.geteuid', return_value=0), \
                 patch('sbmanager.app.StateStore', return_value=store), \
                 patch('sbmanager.app.Deployment'), \
                 patch('sbmanager.app.Systemd'), \
                 patch('sbmanager.app.SingBox') as engine, \
                 patch('builtins.input', side_effect=['1', '5', '0', '0']) as reader, \
                 contextlib.redirect_stdout(output):
                self.assertEqual(0, main())
            self.assertEqual(2, output.getvalue().count('主菜单'))
            self.assertEqual(2, output.getvalue().count('\n  节点管理\n'))
            self.assertNotIn('首次设置向导', output.getvalue())
            self.assertEqual(4, reader.call_count)
            engine.return_value.version.assert_not_called()
            self.assertFalse(store.path.exists())

    def test_startup_always_connects_service_and_shows_menu_without_initializing(self):
        for populated in (False, True):
            with self.subTest(populated=populated), tempfile.TemporaryDirectory() as directory:
                store = StateStore(Path(directory) / 'state')
                if populated:
                    Manager(store).add_inbound('REALITY', 'reality')
                before = store.path.read_bytes() if store.path.exists() else None
                engine = Mock()
                output = io.StringIO()
                with patch('sys.argv', ['sbmanager']), \
                     patch('sbmanager.app.platform.system', return_value='Linux'), \
                     patch('sbmanager.app.os.geteuid', return_value=0), \
                     patch('sbmanager.app.StateStore', return_value=store) as state_store, \
                     patch('sbmanager.app.SingBox', return_value=engine), \
                     patch('sbmanager.app.Systemd') as systemd, \
                     patch('sbmanager.app.Deployment') as deployment, \
                     patch('builtins.input', return_value='0') as reader, \
                     contextlib.redirect_stdout(output):
                    self.assertEqual(0, main())
                state_store.assert_called_once_with(Path('/var/lib/sbmanager'))
                systemd.assert_called_once_with()
                deployment.assert_called_once_with(
                    store, '/etc/sbmanager/config.json', engine, systemd.return_value)
                self.assertIs(store.deployment, deployment.return_value)
                self.assertIn('  SING-BOX MANAGER\n  主菜单\n', output.getvalue())
                self.assertNotIn('首次设置：', output.getvalue())
                self.assertEqual(1, reader.call_count)
                engine.version.assert_not_called()
                deployment.return_value.service.restart.assert_not_called()
                after = store.path.read_bytes() if store.path.exists() else None
                self.assertEqual(before, after)

    def test_unsupported_host_or_permissions_fail_before_creating_state(self):
        for system, uid in (('Darwin', 0), ('Windows', 0), ('Linux', 1000)):
            with self.subTest(system=system, uid=uid), \
                 patch('sys.argv', ['sbmanager']), \
                 patch('sbmanager.app.platform.system', return_value=system), \
                 patch('sbmanager.app.os.geteuid', return_value=uid), \
                 patch('sbmanager.app.StateStore') as state_store, \
                 patch('sbmanager.app.Systemd') as systemd, \
                 contextlib.redirect_stderr(io.StringIO()) as error:
                with self.assertRaises(SystemExit) as exit_result:
                    main()
                self.assertEqual(1, exit_result.exception.code)
                self.assertIn('Linux 和 root 权限', error.getvalue())
                state_store.assert_not_called()
                systemd.assert_not_called()

    def test_help_lists_only_engine_option(self):
        output = io.StringIO()
        with patch('sys.argv', ['sbmanager', '--help']), \
             contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
            main()
        self.assertEqual(0, result.exception.code)
        self.assertEqual(
            ['usage: sbmanager [-h] [--sing-box SING_BOX]'],
            output.getvalue().splitlines()[:1])

    def test_custom_engine_is_passed_to_deployment(self):
        with patch('sys.argv', ['sbmanager', '--sing-box', '/opt/custom/sing-box']), \
             patch('sbmanager.app.platform.system', return_value='Linux'), \
             patch('sbmanager.app.os.geteuid', return_value=0), \
             patch('sbmanager.app.StateStore') as store, \
             patch('sbmanager.app.Systemd') as service, \
             patch('sbmanager.app.SingBox') as engine, \
             patch('sbmanager.app.Deployment') as deployment, \
             patch('sbmanager.app.run', return_value=0) as menu:
            self.assertEqual(0, main())
        engine.assert_called_once_with('/opt/custom/sing-box')
        deployment.assert_called_once_with(
            store.return_value, '/etc/sbmanager/config.json', engine.return_value, service.return_value)
        self.assertIs(store.return_value.deployment, deployment.return_value)
        self.assertIs(menu.call_args.args[2], deployment.return_value)
