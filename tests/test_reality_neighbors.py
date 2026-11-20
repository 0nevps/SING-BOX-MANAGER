import contextlib
import io
import ipaddress
import ssl
import unittest
from unittest.mock import MagicMock, patch

from sbmanager import cli
from sbmanager.system import reality_neighbors as neighbors


class NeighborTests(unittest.TestCase):
    entry = ipaddress.IPv4Address('8.8.8.1')
    target = ipaddress.IPv4Address('8.8.8.2')

    def test_route_boundaries_multiple_addresses_and_ranking(self):
        network = ipaddress.IPv4Network('8.8.8.0/25')
        peer = ipaddress.IPv4Address('8.8.8.3')
        outside = ipaddress.IPv4Address('8.8.8.130')
        samples = {self.target: iter([5, None, 1]), peer: iter([10, 12, 11])}

        def route(ip):
            if ip == self.target:
                return ipaddress.IPv4Network('8.8.8.0/28'), {20}
            return network, {10}

        with patch.object(neighbors, 'routing', side_effect=route), \
             patch.object(neighbors, 'certificate_domains', return_value={'site.example'}) as source, \
             patch.object(neighbors, 'addresses', return_value=[outside, self.target, self.entry, peer]), \
             patch.object(neighbors, 'handshake', side_effect=lambda name, ip, port: next(samples[ip])), \
             patch.object(neighbors, 'http_status', return_value='HTTP/2 301'):
            rows, notes = neighbors.recommend(self.entry, [self.entry], 443)
        source.assert_called_once_with(network)
        self.assertFalse(notes)
        self.assertIn('同宣告前缀 · 同 ASN · 3/3 次成功 · 中位 11.0 ms', rows[0][1])
        self.assertIn('同 /24 · 不同宣告前缀 · 不同 ASN · 2/3 次成功', rows[1][1])

    def test_source_failure_is_not_empty_success(self):
        with patch.object(neighbors, 'routing', return_value=(None, set())), \
             patch.object(neighbors, 'certificate_domains', side_effect=neighbors.LookupFailure('timeout')):
            rows, notes = neighbors.recommend(self.entry, [self.entry], 443)
        self.assertFalse(rows)
        self.assertIn('证书数据源查询失败', ' '.join(notes))

    def test_exhausted_budget_is_reported(self):
        with patch.object(neighbors, 'PAIR_LIMIT', 1), \
             patch.object(neighbors, 'routing', return_value=(None, set())), \
             patch.object(neighbors, 'certificate_domains', return_value={'a.example', 'b.example'}), \
             patch.object(neighbors, 'addresses', return_value=[] ) as resolve:
            rows, notes = neighbors.recommend(self.entry, [self.entry], 443)
        self.assertFalse(rows)
        self.assertIn('预算已用尽', ' '.join(notes))
        self.assertEqual(1, resolve.call_count)

    def test_handshake_pins_address_and_checks_h2(self):
        with patch.object(neighbors.ssl, 'create_default_context') as factory, \
             patch.object(neighbors.socket, 'create_connection') as connect:
            context = factory.return_value
            tls = context.wrap_socket.return_value.__enter__.return_value
            tls.selected_alpn_protocol.return_value = 'http/1.1'
            self.assertIsNone(neighbors.handshake('site.example', self.target, 8443))
            connect.assert_called_once_with((str(self.target), 8443), timeout=3)
            self.assertEqual('site.example', context.wrap_socket.call_args.kwargs['server_hostname'])
            self.assertEqual(ssl.TLSVersion.TLSv1_3, context.minimum_version)

    def test_http_uses_same_address_and_keeps_redirect_status(self):
        with patch.object(neighbors.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '2 301'
            self.assertEqual('HTTP/2 301', neighbors.http_status('site.example', self.target, 8443))
            self.assertIn('site.example:8443:8.8.8.2', run.call_args.args[0])

    def test_cancel_before_write_and_manual_fallback(self):
        manager = MagicMock()
        manager.store.read.return_value = {'inbounds': {}}
        with contextlib.redirect_stdout(io.StringIO()), \
             patch.object(neighbors, 'addresses', return_value=[self.entry, self.target]), \
             patch.object(neighbors, 'recommend', return_value=([('site.example', '候选')], [])) as discover, \
             patch('builtins.input', side_effect=['1', '', '', 'node.example', '2', '2', '0']), \
             self.assertRaises(cli.Cancelled):
            cli.edit_node(manager, MagicMock(), adding=True)
        discover.assert_called_once_with(self.target, [self.entry, self.target], 443)
        manager.store.update.assert_not_called()
        with contextlib.redirect_stdout(io.StringIO()), patch.object(neighbors, 'addresses', return_value=[]), \
             patch('builtins.input', side_effect=['2', 'manual.example']):
            self.assertEqual('manual.example', cli.reality_target('node.example', {}))
