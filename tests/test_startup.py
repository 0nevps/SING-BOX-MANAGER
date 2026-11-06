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
    def test_wizard_requires_menu_selection_and_cancel_returns_to_menu(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with patch('sys.argv', ['main.py', '--state-dir', directory]), \
                 patch('sbmanager.app.SingBox') as engine, \
                 patch('builtins.input', side_effect=['1', '4', '0', '0', '0']) as reader, \
                 contextlib.redirect_stdout(output):
                self.assertEqual(0, main())
            self.assertEqual(2, output.getvalue().count('主菜单'))
            self.assertEqual(2, output.getvalue().count('\n节点管理\n'))
            self.assertIn('选择要安装的节点', reader.call_args_list[2].args[0])
            engine.return_value.version.assert_not_called()
            self.assertFalse((Path(directory) / 'state.json').exists())

    def test_system_startup_always_shows_menu_without_initializing(self):
        for populated in (False, True):
            with self.subTest(populated=populated), tempfile.TemporaryDirectory() as directory:
                store = StateStore(Path(directory) / 'state')
                if populated:
                    Manager(store).add_inbound('REALITY', 'reality')
                before = store.path.read_bytes() if store.path.exists() else None
                engine = Mock()
                output = io.StringIO()
                with patch('sys.argv', ['sbmanager', '--system']), \
                     patch('sbmanager.app.platform.system', return_value='Linux'), \
                     patch('sbmanager.app.os.geteuid', return_value=0), \
                     patch('sbmanager.app.StateStore', return_value=store), \
                     patch('sbmanager.app.SingBox', return_value=engine), \
                     patch('sbmanager.app.Deployment') as deployment, \
                     patch('sbmanager.modules.initialization.wizard') as wizard, \
                     patch('builtins.input', return_value='0') as reader, \
                     contextlib.redirect_stdout(output):
                    self.assertEqual(0, main())
                self.assertIn('主菜单', output.getvalue())
                self.assertNotIn('首次设置：', output.getvalue())
                self.assertEqual(1, reader.call_count)
                wizard.assert_not_called()
                engine.version.assert_not_called()
                deployment.return_value.service.restart.assert_not_called()
                after = store.path.read_bytes() if store.path.exists() else None
                self.assertEqual(before, after)
