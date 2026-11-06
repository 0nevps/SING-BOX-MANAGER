from sbmanager.egress.drivers import http, shadowsocks, socks5
from sbmanager.security import ValidationError

DRIVERS = {'http': http, 'socks5': socks5, 'ss': shadowsocks}


def driver(protocol):
    if protocol not in DRIVERS:
        raise ValidationError('出口协议不支持，目前仅支持 HTTP、SOCKS5、SS')
    return DRIVERS[protocol]
