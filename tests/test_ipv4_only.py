"""IPv4-only applies to node direct traffic, not proxy exits or forwards."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sbmanager.cli import run
from sbmanager.core.config_builder import build
from sbmanager.core.state_manager import StateStore
from sbmanager.core.transaction_manager import Deployment
from sbmanager.modules.manager import Manager
from sbmanager.security import ValidationError
from sbmanager.system.singbox import SingBox
from test_deployment import Engine, Service


class IPv4OnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / 'state')
        self.manager = Manager(self.store)
        self.uid = self.manager.add_user('Alice')
        self.iid = self.manager.add_inbound('REALITY', 'reality')
        self.manager.grant(self.uid, self.iid)
        self.store.update(lambda state: state['inbounds'][self.iid].update(settings={
            'port': 1443, 'server_name': 'example.com', 'handshake': 'example.com',
            'private_key': 'EPkO3Cq2YtGCxO-qPTGR8RLRoY2lgKiu_Vc4OghYCl0',
            'short_id': 'abcdef0123456789'}))

    def deploy(self):
        self.engine, self.service = Engine(), Service()
        self.deployment = Deployment(self.store, Path(self.temp.name) / 'config.json',
                                     self.engine, self.service)
        self.store.deployment = self.deployment
        self.store.update(lambda state: state.update(deployed=True))

    def run_menu(self, answers):
        output = io.StringIO()
        with patch('builtins.input', side_effect=answers) as reader, \
                contextlib.redirect_stdout(output):
            self.assertEqual(0, run(self.manager, Mock(), Mock()))
        return output.getvalue(), '\n'.join(call.args[0] for call in reader.call_args_list)

    def test_legacy_default_and_disable_restore_original_config(self):
        original = build(self.store.read())
        self.assertNotIn('direct_ipv4_only', self.store.read())
        self.manager.set_direct_ipv4_only(True)
        self.manager.set_direct_ipv4_only(False)
        self.assertEqual(original, build(self.store.read()))
        self.assertIs(False, StateStore(self.store.directory).read()['direct_ipv4_only'])

    def test_enable_limits_node_direct_outbound_and_preserves_listener(self):
        self.manager.set_direct_ipv4_only(True)
        config = build(self.store.read())
        self.assertEqual('::', config['inbounds'][0]['listen'])
        self.assertEqual({'type': 'direct', 'tag': 'direct'}, config['outbounds'][0])
        self.assertEqual({'server': 'local-dns', 'strategy': 'ipv4_only'},
                         config['outbounds'][1]['domain_resolver'])
        self.assertEqual('direct-ipv4', config['outbounds'][1]['tag'])
        self.assertEqual([{'type': 'local', 'tag': 'local-dns'}], config['dns']['servers'])
        self.assertEqual([
            {'inbound': [self.iid], 'ip_version': 6, 'action': 'reject'},
            {'inbound': [self.iid], 'action': 'route', 'outbound': 'direct-ipv4'},
        ], config['route']['rules'])
        self.assertNotIn('domain_strategy', json.dumps(config))
        self.assertIs(True, StateStore(self.store.directory).read()['direct_ipv4_only'])

    def test_invalid_flags_never_write(self):
        before = self.store.path.read_bytes()
        for value in (None, 0, 1, 'true', [], {}):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    self.manager.set_direct_ipv4_only(value)
                with self.assertRaises(ValidationError):
                    self.store.update(lambda state: state.update(direct_ipv4_only=value))
                self.assertEqual(before, self.store.path.read_bytes())

    def test_proxy_rules_precede_restriction_and_forward_stays_unrestricted(self):
        eid = self.manager.save_egress('proxy', 'socks5', {
            'server': '2001:db8::1', 'port': 1080, 'udp': False})
        self.manager.bind(self.uid, self.iid, eid)
        forward = self.manager.add_forward({'name': 'IPv6 forward', 'listen_port': 18080,
                                           'target': '::1', 'target_port': 8080})
        original = build(self.store.read())
        self.manager.set_direct_ipv4_only(True)
        config = build(self.store.read())
        rules = config['route']['rules']
        self.assertEqual(original['route']['rules'][:2], rules[:2])
        self.assertEqual(eid, rules[1]['outbound'])
        self.assertEqual('reject', rules[2]['action'])
        self.assertEqual('direct-ipv4', rules[3]['outbound'])
        self.assertEqual({'inbound': ['forward-' + forward], 'action': 'route',
                          'outbound': 'direct'}, rules[-1])
        self.assertEqual(original['outbounds'][1], config['outbounds'][2])
        self.assertEqual(original['inbounds'], config['inbounds'])
        self.manager.bind(self.uid, self.iid)
        self.assertEqual('reject', build(self.store.read())['route']['rules'][0]['action'])

    def test_all_node_protocols_receive_restriction(self):
        for protocol, port in (('hysteria2', 2443), ('cloudflare_ws', 8443), ('anytls', 3443)):
            iid = self.manager.add_inbound(protocol, protocol)
            self.manager.grant(self.uid, iid)
            self.store.update(lambda state: state['inbounds'][iid].update(settings={
                'port': port, 'server_name': 'example.com', 'path': '/gateway'}))
        self.manager.set_direct_ipv4_only(True)
        config = build(self.store.read())
        for node in config['inbounds']:
            self.assertIn({'inbound': [node['tag']], 'ip_version': 6, 'action': 'reject'},
                          config['route']['rules'])
            self.assertIn({'inbound': [node['tag']], 'action': 'route',
                           'outbound': 'direct-ipv4'}, config['route']['rules'])

    def test_toggle_before_nodes_exist_and_forward_only(self):
        self.manager.delete_inbound(self.iid)
        self.manager.set_direct_ipv4_only(True)
        self.manager.add_forward({'name': 'IPv6 forward', 'listen_port': 18080,
                                 'target': '::1', 'target_port': 8080})
        config = build(self.store.read())
        self.assertNotIn('dns', config)
        self.assertEqual([{'type': 'direct', 'tag': 'direct'}], config['outbounds'])
        self.assertEqual(1, len(config['route']['rules']))
        self.assertEqual('direct', config['route']['rules'][0]['outbound'])

    def test_failed_check_and_restart_preserve_flag_and_configuration(self):
        self.deploy()
        for failure in ('check', 'restart'):
            for enabled in (True, False):
                with self.subTest(failure=failure, enabled=enabled):
                    self.manager.set_direct_ipv4_only(not enabled)
                    before = self.store.path.read_bytes(), self.deployment.config_path.read_bytes()
                    self.engine.fail = failure == 'check'
                    self.service.fail_once = failure == 'restart'
                    with self.assertRaises(ValidationError):
                        self.manager.set_direct_ipv4_only(enabled)
                    self.assertEqual(before, (self.store.path.read_bytes(),
                                              self.deployment.config_path.read_bytes()))
                    self.assertTrue(self.service.running)
                    self.assertFalse(self.deployment.journal.exists())
                    self.engine.fail = False

    def test_backup_restore_preserves_setting_and_old_backup_defaults_off(self):
        self.deploy()
        with self.store.locked():
            old_backup = self.deployment.backup()
        self.manager.set_direct_ipv4_only(True)
        with self.store.locked():
            enabled_backup = self.deployment.backup()
        self.manager.set_direct_ipv4_only(False)
        with self.store.locked():
            self.deployment.restore(enabled_backup)
        self.assertIs(True, self.store.read()['direct_ipv4_only'])
        self.assertIn('dns', json.loads(self.deployment.config_path.read_text()))
        with self.store.locked():
            self.deployment.restore(old_backup)
        self.assertNotIn('direct_ipv4_only', self.store.read())
        self.assertNotIn('dns', json.loads(self.deployment.config_path.read_text()))

    def test_cli_status_enable_disable_and_confirmation(self):
        output, prompts = self.run_menu(['7', '1', '1', 'y', '1', '2', 'y', '0', '0'])
        self.assertIn('节点流量仅用 IPv4', output)
        self.assertIn('当前状态：已关闭', output)
        self.assertIn('当前状态：已开启', output)
        self.assertIn('代理出口的流量不受此设置控制', ''.join(output.split()))
        self.assertIn('不影响客户端通过 IPv6 连接节点', output)
        self.assertIn('不影响端口转发', output)
        self.assertIn('连接可能短暂中断', prompts)
        self.assertIs(False, self.store.read()['direct_ipv4_only'])

    def test_cli_cancel_and_noop_do_not_write(self):
        before = self.store.path.read_bytes()
        for answers in (['7', '1', '0', '0', '0'],
                        ['7', '1', '1', 'n', '0', '0'],
                        ['7', '1', '2', '0', '0']):
            with self.subTest(answers=answers):
                self.run_menu(answers)
                self.assertEqual(before, self.store.path.read_bytes())

    def test_cli_failed_apply_does_not_report_success(self):
        self.deploy()
        self.service.fail_once = True
        before = self.store.path.read_bytes()
        output, _ = self.run_menu(['7', '1', '1', 'y', '0', '0'])
        self.assertIn('操作未完成', output)
        self.assertNotIn('节点流量仅用 IPv4已开启', output)
        self.assertEqual(before, self.store.path.read_bytes())

    @unittest.skipUnless(os.environ.get('SING_BOX_TEST_BINARY'),
                         'set SING_BOX_TEST_BINARY for official engine check')
    def test_official_engine(self):
        engine = SingBox(os.environ['SING_BOX_TEST_BINARY'])
        engine.version()
        candidate = Path(self.temp.name) / 'check.json'
        for enabled in (True, False):
            self.manager.set_direct_ipv4_only(enabled)
            candidate.write_text(json.dumps(build(self.store.read())))
            engine.check(candidate)


if __name__ == '__main__':
    unittest.main()
