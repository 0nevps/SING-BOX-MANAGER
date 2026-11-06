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


def websocket_path(value, existing=None):
    path = value or existing or '/' + secrets.token_urlsafe(16)
    path = text(path, 'WS 路径')
    if not path.startswith('/') or any(c in path for c in ('?', '#', ' ')):
        raise ValidationError('WS 路径必须以 / 开头，且不包含空格、查询串或片段')
    return path


def ask_inbound_ports(ask, protocol, previous=None):
    previous = previous or {}
    if (previous.get('port') and previous.get('public_port') != previous['port']
            and previous.get('public_port') and 'connection_mode' not in previous):
        print(f'现有端口转发：手机/电脑连接 {previous["public_port"]}，VPS 上使用 {previous["port"]}。')
        choice = ask('端口设置：1 保留现有设置，2 重新设置（默认 1）') or '1'
        if choice == '1':
            return {'port': previous['port'], 'public_port': previous['public_port']}
        if choice != '2':
            raise ValidationError('请选择 1 或 2')

    labels = {'reality': ('REALITY', 'TCP', 443), 'hysteria2': ('Hysteria2', 'UDP', 443),
              'cloudflare_ws': ('WebSocket', 'TCP', 8443)}
    label, transport, default = labels[protocol]
    mode = 'direct'
    if protocol == 'cloudflare_ws':
        current_mode = previous.get('connection_mode')
        if current_mode is None and previous.get('port') == previous.get('public_port') and previous.get('port'):
            current_mode = 'direct'
        default_choice = '2' if current_mode == 'direct' else '1'
        choice = ask(f'WebSocket 连接方式：1 经过 Cloudflare 代理，2 直连 VPS（默认 {default_choice}）') or default_choice
        if choice not in ('1', '2'):
            raise ValidationError('请选择 1 或 2')
        mode = 'cloudflare' if choice == '1' else 'direct'
    default = previous.get('port', default)
    try:
        port = int(ask(f'{label} 在 VPS 上使用的端口（{transport}，默认 {default}）') or default)
    except ValueError:
        raise ValidationError('端口必须是 1–65535 之间的整数') from None
    if not 1 <= port <= 65535:
        raise ValidationError('端口范围为 1–65535')
    public_port = 443 if mode == 'cloudflare' else port
    if mode == 'cloudflare':
        print(f'手机/电脑连接 Cloudflare 的 HTTPS 443；请在 Cloudflare 将回源端口设为 VPS 的 {port}。')
    else:
        print(f'{label}：手机/电脑连接时也使用 {port} 端口。')
    result = {'port': port, 'public_port': public_port}
    if protocol == 'cloudflare_ws':
        result['connection_mode'] = mode
    return result


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
        values['path'] = websocket_path(values.get('path'), inbound.get('settings', {}).get('path'))
    def change(state):
        state['inbounds'][inbound_id]['settings'] = values
    manager.store.update(change)


def ask_reality_names(ask):
    target = host(ask('REALITY 握手目标域名'))
    server_name = host(ask(f'REALITY SNI（默认 {target}，回车使用默认值）') or target)
    return target, server_name
