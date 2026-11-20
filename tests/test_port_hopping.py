from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sbmanager.core.forwarding import check_forward_conflict
from sbmanager.core.port_hopping import hopping_rules
from sbmanager.security import PortInUse, ValidationError
from sbmanager.system.port_hopping import sync


class PortHoppingTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'port': 443, 'hop_range': '20000-30000'}
        self.state = {'inbounds': {'hy': {'settings': self.settings, 'protocol': 'hysteria2'}}}

    def test_malformed_or_unusable_range(self):
        for value in ('0-2', '2-1', '2-2', '1-65536', '1:3', '1-2\n', None, 443):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.settings['hop_range'] = value
                hopping_rules(self.state)

    def test_conflicts_include_boundary_and_only_affect_udp(self):
        for settings in ({'port': 30000}, {'port': 1443, 'hop_range': '10000-20000'}):
            self.state['inbounds']['other'] = {'protocol': 'hysteria2', 'settings': settings}
            with self.assertRaises(PortInUse):
                hopping_rules(self.state)
        del self.state['inbounds']['other']
        for network in ('udp', 'both'):
            with self.assertRaises(PortInUse):
                check_forward_conflict(self.state, {'network': network, 'listen_port': 20000})
        check_forward_conflict(self.state, {'network': 'tcp', 'listen_port': 20000})

    def test_nft_batch_apply_clear_and_inactive_noop(self):
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.run') as run:
            marker = Path(directory) / 'active'
            sync([], marker)
            run.assert_not_called()
            sync(hopping_rules(self.state), marker)
            script = run.call_args.kwargs['input']
            self.assertIn('fib daddr type local udp dport 20000-30000 redirect to :443', script)
            self.assertNotIn('flush ruleset', script)
            self.assertTrue(marker.exists())
            sync([], marker)
            self.assertTrue(run.call_args.kwargs['input'].endswith('delete table inet sbmanager_hy2\n'))
            self.assertFalse(marker.exists())
            run.side_effect = subprocess.CalledProcessError(1, 'nft')
            with self.assertRaises(subprocess.CalledProcessError):
                sync(hopping_rules(self.state), marker)
            self.assertFalse(marker.exists())
