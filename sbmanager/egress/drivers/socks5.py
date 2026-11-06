"""SOCKS5 profile validation. UDP support is a declaration, not a probe result."""
import ipaddress
import re
from sbmanager.security import ValidationError, text


def validate(values):
    host = text(values.get('server'), '服务器地址')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host.rstrip('.').split('.')
        if len(host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', x) for x in labels):
            raise ValidationError('服务器必须是 IP 地址或域名')
    port = values.get('port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValidationError('端口必须介于 1 和 65535')
    if type(values.get('udp', False)) is not bool:
        raise ValidationError('UDP 能力必须是布尔值')
    for field in ('username', 'password'):
        if len(text(values.get(field), field).encode()) > 255:
            raise ValidationError('SOCKS5 凭据不能超过 255 字节')
    return {'server': host, 'port': port,
            'username': text(values.get('username'), '用户名'),
            'password': text(values.get('password'), '密码'),
            'udp': values.get('udp', False)}


def get_schema():
    return ('server', 'port', 'username', 'password', 'udp')


def build_outbound(profile):
    settings = validate(profile['settings'])
    return {'type': 'socks', 'tag': profile['id'], 'server': settings['server'],
            'server_port': settings['port'], 'version': '5',
            'username': settings['username'], 'password': settings['password']}


def get_capabilities(profile):
    return {'tcp': True, 'udp': profile['settings']['udp'], 'udp_verified': False}


def get_display_info(profile):
    return {'name': profile['name'], 'server': profile['settings']['server'],
            'capabilities': get_capabilities(profile)}


def test_connection(profile, timeout=5):
    """Verify SOCKS5 username/password authentication, not UDP reachability."""
    import socket
    settings = validate(profile['settings'])
    username, password = settings['username'].encode(), settings['password'].encode()
    if len(username) > 255 or len(password) > 255:
        raise ValidationError('SOCKS5 用户名和密码不能超过 255 字节')
    def receive(sock, count):
        result = b''
        while len(result) < count:
            part = sock.recv(count - len(result))
            if not part:
                raise ValidationError('SOCKS5 服务提前关闭连接')
            result += part
        return result
    with socket.create_connection((settings['server'], settings['port']), timeout) as sock:
        sock.sendall(b'\x05\x01\x02')
        if receive(sock, 2) != b'\x05\x02':
            raise ValidationError('SOCKS5 服务不接受用户名密码认证')
        sock.sendall(b'\x01' + bytes([len(username)]) + username + bytes([len(password)]) + password)
        if receive(sock, 2) != b'\x01\x00':
            raise ValidationError('SOCKS5 认证失败')
    return {'authenticated': True, 'udp_verified': False,
            'note': '仅验证协议与认证；尚未验证目标转发或 UDP ASSOCIATE'}
