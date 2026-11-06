import ipaddress
import re
import secrets
from sbmanager.security import ValidationError, text, identifier
from sbmanager.system.network import check_reality_target

PROTOCOL_LABELS = {'reality': 'VLESS + REALITY + Vision', 'hysteria2': 'Hysteria2',
                   'cloudflare_ws': 'VLESS + WebSocket + TLS'}


def host(value):
    value = text(value, 'IP 地址或域名')
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        if len(value) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', p) for p in value.rstrip('.').split('.')):
            raise ValidationError('IP 地址或域名格式不正确。请只填写地址，不要加 http://、端口或路径')
        return value


def websocket_path(value, existing=None):
    path = value or existing or '/' + secrets.token_urlsafe(16)
    path = text(path, 'WebSocket 路径')
    if not path.startswith('/') or any(c in path for c in ('?', '#', ' ')):
        raise ValidationError('WebSocket 路径必须以 / 开头，例如 /proxy；不能包含空格、? 或 #')
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

    label = PROTOCOL_LABELS[protocol]
    transport, default = ('UDP', 443) if protocol == 'hysteria2' else ('TCP', 8443 if protocol == 'cloudflare_ws' else 443)
    mode = 'direct'
    if protocol == 'cloudflare_ws':
        current_mode = previous.get('connection_mode')
        if current_mode is None and previous.get('port') == previous.get('public_port') and previous.get('port'):
            current_mode = 'direct'
        default_choice = '2' if current_mode == 'direct' else '1'
        choice = ask(f'WebSocket 连接方式（默认 {default_choice}）\n1 Cloudflare 代理\n2 直连 VPS') or default_choice
        if choice not in ('1', '2'):
            raise ValidationError('请选择 1 或 2')
        mode = 'cloudflare' if choice == '1' else 'direct'
    default = previous.get('port', default)
    try:
        port = int(ask(f'{label} 在 VPS 上使用的端口（{transport}，默认 {default}）') or default)
    except ValueError:
        raise ValidationError('端口必须是 1–65535 之间的整数') from None
    if not 1 <= port <= 65535:
        raise ValidationError('端口必须是 1–65535 之间的整数，请重新填写')
    public_port = 443 if mode == 'cloudflare' else port
    if mode == 'cloudflare':
        print(f'客户端端口：443；VPS 端口：{port}。\n请手动设置 Cloudflare 回源端口为 {port}。')
    result = {'port': port, 'public_port': public_port}
    if protocol == 'cloudflare_ws':
        result['connection_mode'] = mode
    return result


def configure(manager, engine, inbound_id, values, *, name=None, protocol=None):
    values = dict(values)
    previous_node = manager.store.read()['inbounds'].get(inbound_id) if inbound_id else None
    if inbound_id and previous_node is None:
        raise ValidationError('节点已删除，请重新选择')
    inbound = previous_node or {'id': identifier(), 'name': text(name, '节点名称'), 'protocol': protocol}
    protocol = protocol or inbound['protocol']
    if protocol not in PROTOCOL_LABELS:
        raise ValidationError('不支持的节点协议')
    if protocol != inbound['protocol']:
        raise ValidationError('节点协议不可修改')
    if inbound['protocol'] == 'reality':
        values['server_name'] = values.get('server_name') or values['handshake']
    for field in ('server_name', 'public_host'):
        values[field] = host(values[field])
    for field in ('port', 'public_port'):
        if type(values.get(field)) is not int or not 1 <= values[field] <= 65535:
            raise ValidationError('端口必须是 1–65535 之间的整数，请重新填写')
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
        if previous_node is not None:
            if state['inbounds'].get(inbound_id) != previous_node:
                raise ValidationError('节点已被其他操作修改，请重新选择')
        elif any(node['name'] == inbound['name'] for node in state['inbounds'].values()):
            raise ValidationError('节点名称已存在')
        state['inbounds'][inbound['id']] = {**inbound, 'settings': values}
        return inbound['id']
    return manager.store.update(change)


def ask_reality_names(ask):
    target = host(ask('REALITY 目标域名（需支持 TLS 1.3）'))
    server_name = host(ask(f'REALITY SNI（默认 {target}）') or target)
    return target, server_name
