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
                raise ValidationError(f'无法使用端口 {port}，可能已被其他程序占用或当前权限不足。请检查端口占用、root 权限和系统网络设置') from None


def check_reality_target(target, server_name, port=443, timeout=5):
    """Verify TCP, TLS 1.3 and trusted hostname validation, not REALITY itself."""
    import ssl
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValidationError('REALITY 目标网站的端口必须是 1–65535 之间的整数，通常使用 443')
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    try:
        with socket.create_connection((target, port), timeout=timeout) as connection:
            with context.wrap_socket(connection, server_hostname=server_name) as tls:
                if tls.version() != 'TLSv1.3':
                    raise ValidationError('目标网站未使用 TLS 1.3，无法通过检查。请换一个支持 TLS 1.3 的目标网站')
    except ssl.SSLCertVerificationError:
        raise ValidationError('目标证书校验失败：请检查 SNI（证书域名）是否与目标网站证书一致，证书是否过期或不受系统信任') from None
    except ssl.SSLError:
        raise ValidationError('目标 TLS 1.3 握手失败：无法建立安全连接。请检查目标网站是否支持 TLS 1.3，以及 SNI（证书域名）是否正确') from None
    except OSError:
        raise ValidationError('目标网站连接失败：请检查域名能否解析、VPS 能否访问该网站，以及目标端口是否正确，也可能是连接超时') from None
    return '目标网站连接、TLS 1.3 和证书域名检查通过；仍需 REALITY 客户端实际连接测试。'
