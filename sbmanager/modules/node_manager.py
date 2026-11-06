import ipaddress
import re
import secrets
from sbmanager.security import ValidationError, text
from sbmanager.system.network import check_reality_target


def host(value):
    value = text(value, '主机名')
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        if len(value) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', p) for p in value.rstrip('.').split('.')):
            raise ValidationError('无效域名或 IP')
        return value


def configure(manager, engine, inbound_id, values):
    values = dict(values)
    inbound = manager.store.read()['inbounds'][inbound_id]
    if inbound['protocol'] == 'reality':
        values['server_name'] = values.get('server_name') or values['handshake']
    for field in ('server_name', 'public_host'):
        values[field] = host(values[field])
    for field in ('port', 'public_port'):
        if type(values.get(field)) is not int or not 1 <= values[field] <= 65535:
            raise ValidationError('端口范围为 1–65535')
    if inbound['protocol'] == 'reality':
        values['handshake'] = host(values['handshake'])
        check_reality_target(values['handshake'], values['server_name'], values.get('handshake_port', 443))
        previous = inbound.get('settings', {})
        if previous.get('private_key'):
            values['private_key'], values['public_key'] = previous['private_key'], previous['public_key']
            values['short_id'] = previous['short_id']
        else:
            values['private_key'], values['public_key'] = engine.keypair()
            values['short_id'] = secrets.token_hex(8)
    elif inbound['protocol'] == 'cloudflare_ws':
        path = text(values.get('path'), 'WS 路径')
        if not path.startswith('/') or any(c in path for c in ('?', '#', ' ')):
            raise ValidationError('WS 路径必须以 / 开头，且不包含空格、查询串或片段')
        values['path'] = path
    def change(state):
        state['inbounds'][inbound_id]['settings'] = values
    manager.store.update(change)


def ask_reality_names(ask):
    target = host(ask('REALITY 握手目标域名'))
    server_name = host(ask(f'REALITY SNI（默认 {target}，回车使用默认值）') or target)
    return target, server_name
