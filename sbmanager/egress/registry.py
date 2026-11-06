from sbmanager.egress.drivers import socks5
from sbmanager.security import ValidationError

DRIVERS = {'socks5': socks5}


def driver(protocol):
    if protocol not in DRIVERS:
        raise ValidationError('出口协议不支持，目前只能添加 SOCKS5（socks5）出口')
    return DRIVERS[protocol]
