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


def check_reality_target(target, server_name, port=443, timeout=5):
    """Verify TCP, TLS 1.3 and trusted hostname validation, not REALITY itself."""
    import ssl
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValidationError('REALITY 握手端口范围为 1–65535')
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    try:
        with socket.create_connection((target, port), timeout=timeout) as connection:
            with context.wrap_socket(connection, server_hostname=server_name) as tls:
                if tls.version() != 'TLSv1.3':
                    raise ValidationError('握手目标未协商 TLS 1.3')
    except ssl.SSLCertVerificationError:
        raise ValidationError('目标证书校验失败：请检查 SNI 是否匹配、证书有效期和信任链') from None
    except ssl.SSLError:
        raise ValidationError('目标 TLS 1.3 握手失败：请检查目标支持情况和 SNI') from None
    except OSError:
        raise ValidationError('握手目标连接失败：请检查 DNS、网络、端口或超时') from None
    return '目标连通性、TLS 1.3 和证书域名校验通过；仍需 REALITY 客户端验证连接。'
