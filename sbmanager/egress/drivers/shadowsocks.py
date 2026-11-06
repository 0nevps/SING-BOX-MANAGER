"""Shadowsocks outbound without plugins."""
import base64
import binascii
from sbmanager.egress.drivers.common import endpoint, tcp_connection
from sbmanager.security import ValidationError

METHODS = {'aes-128-gcm', 'aes-192-gcm', 'aes-256-gcm', 'chacha20-ietf-poly1305',
           'xchacha20-ietf-poly1305', '2022-blake3-aes-128-gcm',
           '2022-blake3-aes-256-gcm', '2022-blake3-chacha20-poly1305'}


def validate(values):
    settings = endpoint(values)
    method, password = values.get('method'), values.get('password')
    if not isinstance(method, str) or method not in METHODS:
        raise ValidationError('不支持此 Shadowsocks 加密方法，请使用 AEAD 或 Shadowsocks 2022')
    if not isinstance(password, str) or not password or any(ord(c) < 32 or ord(c) == 127 for c in password):
        raise ValidationError('Shadowsocks 密码不能为空或包含控制字符')
    if method.startswith('2022-'):
        size = 16 if method == '2022-blake3-aes-128-gcm' else 32
        try:
            if any(len(base64.b64decode(key, validate=True)) != size for key in password.split(':')):
                raise ValueError()
        except (ValueError, binascii.Error):
            raise ValidationError('Shadowsocks 2022 密钥格式或长度不正确') from None
    return {**settings, 'method': method, 'password': password}


def build_outbound(profile):
    settings = validate(profile['settings'])
    return {'type': 'shadowsocks', 'tag': profile['id'], 'server': settings['server'],
            'server_port': settings['port'], 'method': settings['method'],
            'password': settings['password']}


def test_connection(profile, timeout=5):
    return tcp_connection(profile, validate, timeout)
