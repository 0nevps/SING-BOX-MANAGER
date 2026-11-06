"""Shared endpoint validation and explicitly limited TCP reachability checks."""
import ipaddress
import re
import socket
from sbmanager.security import ValidationError, text


def endpoint(values):
    host = text(values.get('server'), '服务器地址')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host.rstrip('.').split('.')
        if len(host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', x) for x in labels):
            raise ValidationError('服务器地址格式不正确，请填写 IP 或域名')
    port = values.get('port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValidationError('出口端口必须是 1–65535 之间的整数')
    if type(values.get('udp', False)) is not bool:
        raise ValidationError('UDP 支持设置必须为 true 或 false')
    return {'server': host, 'port': port, 'udp': values.get('udp', False)}


def authentication(values):
    username, password = values.get('username', ''), values.get('password', '')
    if not isinstance(username, str) or not isinstance(password, str):
        raise ValidationError('出口用户名和密码必须是字符串')
    if bool(username) != bool(password):
        raise ValidationError('出口用户名和密码必须同时填写或同时省略')
    for value in (username, password):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValidationError('出口用户名和密码不能包含控制字符')
    return {'username': username, 'password': password}


def tcp_connection(profile, validate, timeout):
    settings = validate(profile['settings'])
    with socket.create_connection((settings['server'], settings['port']), timeout):
        pass
    return {'authenticated': False, 'udp_verified': False,
            'note': 'TCP 端口可连接；未验证代理协议、密码、实际转发或 UDP'}
