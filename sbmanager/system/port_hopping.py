import json
from pathlib import Path
import subprocess
import sys

from sbmanager.core.port_hopping import hopping_rules


TABLE = 'inet sbmanager_hy2'
MARKER = Path('/run/sbmanager-hy2.active')


def sync(ranges, marker=MARKER):
    previously_managed = marker.exists()
    if not ranges and not previously_managed:
        return
    commands = [f'add table {TABLE}', f'delete table {TABLE}']
    if ranges:
        commands.extend([f'add table {TABLE}',
                         f'add chain {TABLE} ingress {{ type nat hook prerouting priority dstnat; policy accept; }}'])
        for start, end, port in ranges:
            commands.append(f'add rule {TABLE} ingress fib daddr type local udp dport {start}-{end} redirect to :{port}')
        marker.touch(mode=0o600)
    try:
        subprocess.run(['nft', '-f', '-'], input='\n'.join(commands) + '\n', text=True, check=True, timeout=15)
    except (subprocess.CalledProcessError, FileNotFoundError):
        if not previously_managed:
            marker.unlink(missing_ok=True)
        raise
    if not ranges:
        marker.unlink(missing_ok=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['clear']:
        sync([])
    elif sys.argv[1:] == ['apply']:
        state_path = Path('/var/lib/sbmanager/state.json')
        sync(hopping_rules(json.loads(state_path.read_text())) if state_path.exists() else [])
    else:
        sys.exit('expected apply or clear')
