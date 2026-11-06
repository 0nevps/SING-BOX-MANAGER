import ipaddress
import socket
import urllib.request
from sbmanager.security import ValidationError


def public_addresses():
    result = {}
    for family, url in [('ipv4', 'https://api4.ipify.org'), ('ipv6', 'https://api6.ipify.org')]:
        try:
            with urllib.request.urlopen(url, timeout=4) as response:
                address = response.read(128).decode().strip()
            parsed = ipaddress.ip_address(address)
            if parsed.is_global:
                result[family] = address
        except (OSError, ValueError):
            pass
    return result


def check_available(config):
    """Local bind checks only. Internet reachability still requires an external probe."""
    listeners = [(i['listen_port'], socket.SOCK_DGRAM if i['type'] == 'hysteria2' else socket.SOCK_STREAM)
                 for i in config['inbounds']]
    if any(i['tls'].get('certificate_provider') for i in config['inbounds']):
        listeners.append((80, socket.SOCK_STREAM))
    for port, kind in listeners:
        with socket.socket(socket.AF_INET6, kind) as sock:
            try:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                sock.bind(('::', port))
            except OSError:
                raise ValidationError(f'端口 {port} 不可绑定或无权限，请检查占用及系统网络配置') from None
