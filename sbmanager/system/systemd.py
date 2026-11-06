import ipaddress
import json
import socket
from sbmanager.system.network import inbound_listeners
import subprocess
import time
from sbmanager.security import ValidationError


class Systemd:
    unit = 'sbmanager-sing-box.service'

    def preflight(self, config):
        from sbmanager.system.network import check_available
        check_available(config)

    def active(self):
        return subprocess.run(['systemctl', 'is-active', '--quiet', self.unit], capture_output=True, timeout=10).returncode == 0

    def restart(self):
        subprocess.run(['systemctl', 'restart', self.unit], capture_output=True, timeout=120, check=True)

    def stop(self):
        subprocess.run(['systemctl', 'stop', self.unit], capture_output=True, timeout=30, check=True)

    def health(self, config):
        for attempt in range(15):
            if self.active():
                result = subprocess.run(['ss', '-H', '-lntu'], capture_output=True, text=True, timeout=10, check=True)
                listeners = set()
                for line in result.stdout.splitlines():
                    fields = line.split()
                    if len(fields) >= 5:
                        try:
                            address, port = fields[4].rsplit(':', 1)
                            address = address.strip('[]')
                            if address != '*':
                                address = str(ipaddress.ip_address(address))
                            listeners.add((fields[0], address, int(port)))
                        except ValueError:
                            pass
                needed = set(inbound_listeners(config))
                if all((protocol, str(ipaddress.ip_address(address)), port) in listeners
                       or (ipaddress.ip_address(address).is_unspecified
                           and (protocol, '*', port) in listeners)
                       for protocol, address, port in needed):
                    return
            time.sleep(1)
        raise ValidationError('服务未正常运行，或节点端口未就绪。请到“服务管理 > 查看日志”排查，并检查端口占用')

    def logs(self):
        # Warn-level engine logs can contain remote addresses; never include config dumps.
        subprocess.run(['journalctl', '-u', self.unit, '-n', '60', '--no-pager'], timeout=15, check=True)
