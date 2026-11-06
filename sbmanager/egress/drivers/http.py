"""HTTP CONNECT proxy outbound."""
from sbmanager.egress.drivers.common import endpoint, authentication, tcp_connection
from sbmanager.security import ValidationError


def validate(values):
    settings = {**endpoint(values), **authentication(values)}
    if settings['udp']:
        raise ValidationError('HTTP 出口不支持 UDP')
    return settings


def build_outbound(profile):
    settings = validate(profile['settings'])
    outbound = {'type': 'http', 'tag': profile['id'], 'server': settings['server'],
                'server_port': settings['port']}
    if settings['username']:
        outbound.update(username=settings['username'], password=settings['password'])
    return outbound


def test_connection(profile, timeout=5):
    return tcp_connection(profile, validate, timeout)
