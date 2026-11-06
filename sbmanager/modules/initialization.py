"""Collect a complete initial deployment before writing state."""
import copy
import secrets
import socket
from sbmanager.modules.node_manager import host, ask_reality_names, websocket_path, ask_inbound_ports
from sbmanager.system.network import check_reality_target
from sbmanager.security import credential, identifier, text, ValidationError


def wizard(manager, engine, ask):
    state = manager.store.read()
    if state['inbounds'] or state['users']:
        raise ValidationError('已有业务数据，请使用入站配置菜单；初始化不会覆盖数据')
    engine.version()
    print('初始化将创建三个入站和一个用户。公网地址可填写 IP 或域名。')
    from sbmanager.system.network import public_addresses
    addresses = public_addresses()
    print('检测到的公网地址（可手动修正）:', addresses or '检测失败')
    default_host = addresses.get('ipv4') or addresses.get('ipv6', '')
    public_host = host(ask(f'服务器公网 IP/域名（默认 {default_host}）') or default_host)
    name = text(ask('首个用户名（默认 default）') or 'default', '用户名')
    handshake, server_name = ask_reality_names(ask)
    print(check_reality_target(handshake, server_name))
    hy_domain = host(ask('Hysteria2 证书域名'))
    ws_domain = host(ask('WebSocket 证书域名'))
    ws_path = websocket_path(ask('WebSocket 路径（回车随机生成）'))
    for domain in (hy_domain, ws_domain):
        try:
            socket.getaddrinfo(domain, 80)
        except OSError:
            raise ValidationError(f'域名解析失败: {domain}') from None
    print('必须确保公网 TCP 80 到达源站；DNS 和本地端口检查不能证明公网可达。')
    private, public = engine.keypair()
    nodes = []
    for protocol, domain in [('reality', server_name), ('hysteria2', hy_domain), ('cloudflare_ws', ws_domain)]:
        settings = {**ask_inbound_ports(ask, protocol), 'server_name': domain,
                    'public_host': public_host if protocol == 'reality' else domain}
        if protocol == 'reality':
            settings.update(private_key=private, public_key=public, short_id=secrets.token_hex(8), handshake=handshake)
        elif protocol == 'cloudflare_ws':
            settings['path'] = ws_path
        nodes.append({'id': identifier(), 'name': protocol.upper(), 'protocol': protocol, 'settings': settings})
    if ask('确认保存初始化资料？输入 yes') != 'yes':
        return
    def initialize(current):
        if current['inbounds'] or current['users']:
            raise ValidationError('状态已被其他操作修改，请重新初始化')
        current['inbounds'] = {node['id']: node for node in nodes}
        uid = identifier()
        current['users'][uid] = {'id': uid, 'name': name, 'enabled': True,
            'grants': {node['id']: credential(node['protocol']) for node in nodes}}
    manager.store.update(initialize)
    print('WebSocket 路径:', ws_path)
    print('初始化资料已保存。选择“校验并部署”启动服务，随后验证客户端和证书。')
