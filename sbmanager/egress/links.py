"""Parse supported proxy links without exposing credentials in errors."""
import base64
import binascii
import re
from urllib.parse import unquote, urlsplit
from sbmanager.egress.registry import driver
from sbmanager.security import ValidationError, text


def decode64(value):
    raw = value.encode('ascii')
    return base64.b64decode(raw + b'=' * (-len(raw) % 4), altchars=b'-_', validate=True).decode('utf-8')


def decoded(value):
    if re.search(r'%(?![0-9a-fA-F]{2})', value):
        raise ValueError()
    return unquote(value, errors='strict')


def parse_link(value):
    """Return protocol, validated settings and optional fragment name; UDP defaults off."""
    try:
        value = text(value, '分享链接')
        if any(c.isspace() or ord(c) == 127 for c in value):
            raise ValueError()
        scheme, separator, body = value.partition('://')
        protocol = scheme.lower()
        if not separator or protocol not in ('http', 'socks5', 'ss'):
            raise ValidationError('出口链接仅支持 http://、socks5://、ss://')
        body, _, fragment = body.partition('#')
        name = text(decoded(fragment), '出口名称') if fragment else ''
        if '?' in body:
            raise ValidationError('暂不支持分享链接中的查询参数或 SS 插件')
        if protocol == 'ss' and '@' not in body:
            body = decode64(body)
        parsed = urlsplit(protocol + '://' + body)
        if parsed.path not in ('', '/') or not parsed.hostname or parsed.port is None:
            raise ValueError()
        settings = {'server': parsed.hostname, 'port': parsed.port, 'udp': False}
        if protocol == 'ss':
            userinfo, separator, _ = parsed.netloc.rpartition('@')
            if not separator:
                raise ValueError()
            userinfo = decoded(userinfo)
            if ':' not in userinfo:
                userinfo = decode64(userinfo)
            method, separator, password = userinfo.partition(':')
            if not separator:
                raise ValueError()
            settings.update(method=method, password=password)
        else:
            settings.update(username=decoded(parsed.username or ''), password=decoded(parsed.password or ''))
        return protocol, driver(protocol).validate(settings), name
    except ValidationError:
        raise
    except (ValueError, UnicodeError, binascii.Error):
        raise ValidationError('分享链接格式不正确，请检查编码、服务器地址和端口') from None
