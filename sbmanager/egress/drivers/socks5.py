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
            raise ValidationError('SOCKS5 服务器地址格式不正确。请填写 IP 或域名，不要加 http://、端口或路径')
    port = values.get('port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValidationError('SOCKS5 端口必须是 1–65535 之间的整数，请按代理服务商提供的端口填写')
    if type(values.get('udp', False)) is not bool:
        raise ValidationError('UDP 支持设置格式不正确，必须为 true（支持）或 false（不支持）')
    for field in ('username', 'password'):
        if len(text(values.get(field), field).encode()) > 255:
            raise ValidationError('SOCKS5 用户名或密码太长，分别不能超过 255 字节；一个中文字符可能占多个字节')
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
                raise ValidationError('SOCKS5 服务器提前断开连接。请核对服务器地址、端口和服务是否正常')
            result += part
        return result
    with socket.create_connection((settings['server'], settings['port']), timeout) as sock:
        sock.sendall(b'\x05\x01\x02')
        if receive(sock, 2) != b'\x05\x02':
            raise ValidationError('这个 SOCKS5 服务器不接受用户名和密码登录，目前无法使用此出口')
        sock.sendall(b'\x01' + bytes([len(username)]) + username + bytes([len(password)]) + password)
        if receive(sock, 2) != b'\x01\x00':
            raise ValidationError('SOCKS5 登录失败。请检查代理服务商提供的用户名和密码')
    return {'authenticated': True, 'udp_verified': False,
            'note': '已连接 SOCKS5 服务器并通过用户名、密码检查；尚未测试能否通过它访问网站，也未测试 UDP 转发'}
