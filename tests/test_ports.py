import unittest
from unittest.mock import Mock

from sbmanager.modules.node_manager import ask_inbound_ports
from sbmanager.security import ValidationError


class PortPromptTests(unittest.TestCase):
    def test_direct_protocols_need_only_one_port(self):
        for protocol in ('reality', 'hysteria2'):
            with self.subTest(protocol=protocol):
                ask = Mock(return_value='2443')
                self.assertEqual({'port': 2443, 'public_port': 2443},
                                 ask_inbound_ports(ask, protocol))
                self.assertEqual(1, ask.call_count)

    def test_cloudflare_and_direct_websocket_ports(self):
        for mode, expected in [('1', 443), ('2', 8443)]:
            with self.subTest(mode=mode):
                ask = Mock(side_effect=[mode, ''])
                result = ask_inbound_ports(ask, 'cloudflare_ws')
                self.assertEqual(8443, result['port'])
                self.assertEqual(expected, result['public_port'])

    def test_edit_retains_direct_mode_and_port(self):
        previous = {'port': 9443, 'public_port': 9443, 'connection_mode': 'direct'}
        result = ask_inbound_ports(Mock(side_effect=['', '']), 'cloudflare_ws', previous)
        self.assertEqual(previous, result)

    def test_legacy_custom_mapping_can_be_preserved(self):
        for protocol in ('reality', 'hysteria2', 'cloudflare_ws'):
            with self.subTest(protocol=protocol):
                previous = {'port': 8443, 'public_port': 9443}
                ask = Mock(return_value='')
                self.assertEqual(previous, ask_inbound_ports(ask, protocol, previous))
                self.assertEqual(1, ask.call_count)

    def test_legacy_mapping_can_be_reconfigured(self):
        previous = {'port': 8443, 'public_port': 9443}
        ask = Mock(side_effect=['2', '2443'])
        self.assertEqual({'port': 2443, 'public_port': 2443},
                         ask_inbound_ports(ask, 'reality', previous))

    def test_invalid_port_and_mode_rejected(self):
        for value in ('0', '65536', 'not-a-port'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ask_inbound_ports(Mock(return_value=value), 'reality')
        with self.assertRaises(ValidationError):
            ask_inbound_ports(Mock(return_value='invalid'), 'cloudflare_ws')
