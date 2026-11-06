import base64
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sbmanager.cli import Cancelled, MENUS, egress_action
from sbmanager.core.config_builder import build
from sbmanager.core.state_manager import StateStore
from sbmanager.egress.links import parse_link
from sbmanager.egress.registry import driver
from sbmanager.modules.manager import Manager
from sbmanager.security import ValidationError


def b64(value):
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip('=')


class EgressLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = Manager(StateStore(Path(self.temp.name) / 'state'))

    def test_supported_formats(self):
        links = [
            ('http://alice:p%40ss@proxy.example:8080/#HTTP', 'http', 'p@ss'),
            ('socks5://alice:p%3Ass@[2001:db8::1]:1080#SOCKS', 'socks5', 'p:ss'),
            ('ss://' + b64('aes-128-gcm:secret') + '@proxy.example:8388#SS', 'ss', 'secret'),
            ('ss://' + b64('aes-128-gcm:secret@proxy.example:8388'), 'ss', 'secret'),
            ('ss://aes-128-gcm:p%40ss@proxy.example:8388', 'ss', 'p@ss'),
        ]
        for link, expected, password in links:
            with self.subTest(protocol=expected):
                protocol, settings, _ = parse_link(link)
                self.assertEqual(expected, protocol)
                self.assertEqual(password, settings['password'])
                self.assertFalse(settings['udp'])
                key = self.manager.save_egress('出口', protocol, settings)
                profile = self.manager.store.read()['egress'][key]
                outbound = driver(protocol).build_outbound(profile)
                self.assertEqual({'http': 'http', 'socks5': 'socks', 'ss': 'shadowsocks'}[protocol], outbound['type'])
                self.assertEqual(settings['port'], outbound['server_port'])

    def test_no_auth(self):
        for protocol in ('http', 'socks5'):
            _, settings, _ = parse_link(f'{protocol}://proxy.example:1080')
            self.assertEqual('', settings['username'])
            self.assertEqual('', settings['password'])

    def test_invalid_links_do_not_leak_secrets_or_write(self):
        for link in ('vless://secret@host:443', 'https://secret@host:443',
                     'ss://invalid', 'ss://aes-128-gcm:secret@host:8388?plugin=x',
                     'http://user:secret@host:0', 'http://user:secret@host:65536',
                     'http://user:secret@host', 'http://user:secret@host:80/path',
                     'http://user:secret%ZZ@host:80', 'http://user:secret%0A@host:80',
                     'socks5://user@host:1080', 'ss://unknown:secret@host:8388',
                     'ss://2022-blake3-aes-128-gcm:secret@host:8388'):
            with self.subTest(link=link):
                before = self.manager.store.read()
                with self.assertRaises(ValidationError) as error:
                    parse_link(link)
                self.assertNotIn('secret', str(error.exception))
                self.assertEqual(before, self.manager.store.read())

    def test_cli_add_edit_and_cancel(self):
        self.assertEqual('添加出口', MENUS[2][1][1])
        with patch('sbmanager.cli.getpass.getpass', return_value='http://host:8080#入口'), \
                patch('builtins.input', return_value=''), contextlib.redirect_stdout(io.StringIO()):
            egress_action(2, self.manager)
        key, profile = next(iter(self.manager.store.read()['egress'].items()))
        self.assertEqual('入口', profile['name'])
        with patch('sbmanager.cli.getpass.getpass', return_value='ss://' + b64('aes-128-gcm:secret') + '@host:8388'), \
                patch('builtins.input', side_effect=['1', '', 'yes']), contextlib.redirect_stdout(io.StringIO()):
            egress_action(5, self.manager)
        profile = self.manager.store.read()['egress'][key]
        self.assertEqual('ss', profile['protocol'])
        self.assertTrue(profile['settings']['udp'])
        self.assertEqual('入口', profile['name'])
        before = self.manager.store.read()
        with patch('sbmanager.cli.getpass.getpass', return_value='0'), self.assertRaises(Cancelled):
            egress_action(2, self.manager)
        self.assertEqual(before, self.manager.store.read())

    def test_udp_rejection_and_binding_preserved(self):
        uid = self.manager.add_user('user')
        iid = self.manager.add_inbound('node', 'hysteria2')
        self.manager.grant(uid, iid)
        self.manager.store.update(lambda state: state['inbounds'][iid].update(settings={
            'port': 443, 'server_name': 'example.com'}))
        for link in ('http://host:8080', 'socks5://host:1080', 'ss://aes-128-gcm:secret@host:8388'):
            protocol, settings, _ = parse_link(link)
            key = self.manager.save_egress('出口', protocol, settings)
            self.manager.bind(uid, iid, key)
            config = build(self.manager.store.read())
            self.assertEqual('reject', config['route']['rules'][0]['action'])
            self.assertEqual('udp', config['route']['rules'][0]['network'])
            self.assertEqual(key, config['route']['rules'][1]['outbound'])
        self.assertNotIn('secret', str(self.manager.summary()))

    def test_connection_checks_report_limits(self):
        for protocol in ('http', 'ss'):
            link = 'http://host:8080' if protocol == 'http' else 'ss://aes-128-gcm:secret@host:8388'
            _, settings, _ = parse_link(link)
            with patch('sbmanager.egress.drivers.common.socket.create_connection'):
                result = driver(protocol).test_connection({'settings': settings})
            self.assertFalse(result['authenticated'])
            self.assertIn('未验证', result['note'])
        for authenticated in (False, True):
            settings = {'server': 'host', 'port': 1080, 'udp': False,
                        'username': 'user' if authenticated else '', 'password': 'secret' if authenticated else ''}
            with patch('socket.create_connection') as connect:
                sock = connect.return_value.__enter__.return_value
                sock.recv.side_effect = [b'\x05\x02', b'\x01\x00'] if authenticated else [b'\x05\x00']
                result = driver('socks5').test_connection({'settings': settings})
            self.assertEqual(authenticated, result['authenticated'])


if __name__ == '__main__':
    unittest.main()
