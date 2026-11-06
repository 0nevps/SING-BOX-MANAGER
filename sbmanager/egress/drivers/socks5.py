"""SOCKS5 profile validation. UDP support is a declaration, not a probe result."""
from sbmanager.egress.drivers.common import endpoint, authentication
from sbmanager.security import ValidationError


def validate(values):
    settings = {**endpoint(values), **authentication(values)}
    if any(len(settings[field].encode()) > 255 for field in ('username', 'password')):
        raise ValidationError('SOCKS5 用户名或密码太长，分别不能超过 255 字节')
    return settings


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
                raise ValidationError('SOCKS5 服务器提前断开连接。请核对服务器地址、端口和服务是否正常')
            result += part
        return result
    with socket.create_connection((settings['server'], settings['port']), timeout) as sock:
        method = b'\x02' if username else b'\x00'
        sock.sendall(b'\x05\x01' + method)
        if receive(sock, 2) != b'\x05' + method:
            raise ValidationError('SOCKS5 服务器不接受指定的认证方式')
        if username:
            sock.sendall(b'\x01' + bytes([len(username)]) + username + bytes([len(password)]) + password)
            if receive(sock, 2) != b'\x01\x00':
                raise ValidationError('SOCKS5 登录失败。请检查代理服务商提供的用户名和密码')
    return {'authenticated': bool(username), 'udp_verified': False,
            'note': 'SOCKS5 握手通过' + ('，用户名、密码检查通过' if username else '（无认证）') +
                    '；尚未测试实际转发或 UDP'}
