from sbmanager.egress.drivers import socks5
from sbmanager.security import ValidationError

DRIVERS = {'socks5': socks5}


def driver(protocol):
    if protocol not in DRIVERS:
        raise ValidationError('不支持的出口协议')
    return DRIVERS[protocol]
