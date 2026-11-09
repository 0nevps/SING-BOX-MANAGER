import errno
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

from sbmanager.security import PortInUse, ValidationError
from sbmanager.system.network import check_available
from sbmanager.system.systemd import Systemd


def direct(address='::', network=None):
    inbound = {'type': 'direct', 'listen': address, 'listen_port': 9000}
    if network is not None:
        inbound['network'] = network
    return {'inbounds': [inbound]}


class ForwardNetworkTests(unittest.TestCase):
    @patch('sbmanager.system.network.socket.socket')
    def test_default_network_checks_both_without_tls(self, factory):
        check_available(direct())
        self.assertEqual(factory.call_args_list, [
            call(socket.AF_INET6, socket.SOCK_STREAM),
            call(socket.AF_INET6, socket.SOCK_DGRAM)])
        self.assertEqual(factory.return_value.__enter__.return_value.bind.call_args_list,
                         [call(('::', 9000)), call(('::', 9000))])

    def test_single_protocol_and_address_family(self):
        for address, family in [('127.0.0.1', socket.AF_INET), ('::1', socket.AF_INET6)]:
            for protocol, kind in [('tcp', socket.SOCK_STREAM), ('udp', socket.SOCK_DGRAM)]:
                with self.subTest(address=address, protocol=protocol), patch(
                        'sbmanager.system.network.socket.socket') as factory:
                    check_available(direct(address, protocol))
                    factory.assert_called_once_with(family, kind)
                    sock = factory.return_value.__enter__.return_value
                    sock.bind.assert_called_once_with((address, 9000))
                    self.assertEqual(sock.setsockopt.called, family == socket.AF_INET6)

    @patch('sbmanager.system.network.socket.socket')
    def test_udp_bind_failure(self, factory):
        factory.return_value.__enter__.return_value.bind.side_effect = [None, OSError()]
        with self.assertRaises(ValidationError):
            check_available(direct())

    def test_occupied_protocol_reports_address_and_port(self):
        for address in ('127.0.0.1', '::1'):
            for protocol in ('tcp', 'udp'):
                with self.subTest(address=address, protocol=protocol), patch(
                        'sbmanager.system.network.socket.socket') as factory:
                    factory.return_value.__enter__.return_value.bind.side_effect = OSError(
                        errno.EADDRINUSE, 'Address already in use')
                    with self.assertRaises(PortInUse) as raised:
                        check_available(direct(address, protocol))
                    self.assertIn(f'{protocol.upper()} [{address}]:9000', str(raised.exception))

    @patch('sbmanager.system.network.socket.socket')
    def test_both_detects_udp_conflict_after_free_tcp(self, factory):
        factory.return_value.__enter__.return_value.bind.side_effect = [
            None, OSError(errno.EADDRINUSE, 'Address already in use')]
        with self.assertRaisesRegex(PortInUse, 'UDP'):
            check_available(direct())

    @patch('sbmanager.system.network.socket.socket')
    def test_non_conflict_bind_failure_is_not_reported_as_occupied(self, factory):
        factory.return_value.__enter__.return_value.bind.side_effect = OSError(
            errno.EADDRNOTAVAIL, 'Cannot assign requested address')
        with self.assertRaises(ValidationError) as raised:
            check_available(direct())
        self.assertNotIsInstance(raised.exception, PortInUse)

    def test_real_occupied_tcp_and_udp_ports(self):
        for protocol, kind in (('tcp', socket.SOCK_STREAM), ('udp', socket.SOCK_DGRAM)):
            with self.subTest(protocol=protocol), socket.socket(socket.AF_INET, kind) as occupied:
                occupied.bind(('127.0.0.1', 0))
                if protocol == 'tcp':
                    occupied.listen()
                config = direct('127.0.0.1', protocol)
                config['inbounds'][0]['listen_port'] = occupied.getsockname()[1]
                with self.assertRaises(PortInUse):
                    check_available(config)
            check_available(config)

    @patch('sbmanager.system.network.socket.socket')
    def test_existing_nodes_and_acme(self, factory):
        check_available({'inbounds': [
            {'type': 'vless', 'listen_port': 443, 'tls': {}},
            {'type': 'hysteria2', 'listen_port': 8443,
             'tls': {'certificate_provider': 'acme'}}]})
        self.assertEqual(factory.call_args_list, [
            call(socket.AF_INET6, socket.SOCK_STREAM),
            call(socket.AF_INET6, socket.SOCK_DGRAM),
            call(socket.AF_INET6, socket.SOCK_STREAM)])
        self.assertEqual(factory.return_value.__enter__.return_value.bind.call_args_list,
                         [call(('::', 443)), call(('::', 8443)), call(('::', 80))])

    def health(self, config, output):
        with patch.object(Systemd, 'active', return_value=True), patch(
                'sbmanager.system.systemd.subprocess.run', return_value=SimpleNamespace(stdout=output)), patch(
                'sbmanager.system.systemd.time.sleep'):
            Systemd().health(config)

    def test_health_both_protocols_ipv4_ipv6(self):
        for address, endpoint in [('127.0.0.1', '127.0.0.1'), ('::1', '[::1]'), ('::', '*')]:
            with self.subTest(address=address):
                self.health(direct(address),
                            f'tcp LISTEN 0 128 {endpoint}:9000 *:*\n'
                            f'udp UNCONN 0 0 {endpoint}:9000 *:*\n')

    def test_health_single_protocol(self):
        for protocol in ('tcp', 'udp'):
            with self.subTest(protocol=protocol):
                self.health(direct('::', protocol), f'{protocol} UNCONN 0 0 [::]:9000 *:*\n')

    def test_health_missing_udp_fails(self):
        with self.assertRaises(ValidationError):
            self.health(direct(), 'tcp LISTEN 0 128 [::]:9000 *:*\n')

    def test_health_wrong_address_fails(self):
        with self.assertRaises(ValidationError):
            self.health(direct('127.0.0.1', 'tcp'), 'tcp LISTEN 0 128 127.0.0.2:9000 *:*\n')

    def test_health_existing_nodes(self):
        self.health({'inbounds': [
            {'type': 'vless', 'listen_port': 443, 'tls': {}},
            {'type': 'hysteria2', 'listen_port': 8443, 'tls': {}}]},
            'tcp LISTEN 0 128 *:443 *:*\nudp UNCONN 0 0 [::]:8443 *:*\n')


if __name__ == '__main__':
    unittest.main()
