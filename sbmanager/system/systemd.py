import json
import socket
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
                            listeners.add((fields[0], int(fields[4].rsplit(':', 1)[1])))
                        except ValueError:
                            pass
                needed = {('udp' if i['type'] == 'hysteria2' else 'tcp', i['listen_port']) for i in config['inbounds']}
                if needed <= listeners:
                    return
            time.sleep(1)
        raise ValidationError('服务未正常运行，或节点端口未就绪。请到“服务管理 > 查看日志”排查，并检查端口占用')

    def logs(self):
        # Warn-level engine logs can contain remote addresses; never include config dumps.
        subprocess.run(['journalctl', '-u', self.unit, '-n', '60', '--no-pager'], timeout=15, check=True)
