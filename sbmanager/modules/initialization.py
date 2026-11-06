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
        raise ValidationError('已有用户或节点，请在“节点管理 > 设置地址和端口”中修改；现有数据不会被覆盖')
    print('首次设置：仅创建选中的节点和一个用户。\n'
          '1 REALITY\n2 Hysteria2\n3 WebSocket\n0 取消')
    while True:
        choices = ask('选择要安装的节点（可多选，用空格或逗号分隔，如 1 3；0 取消）').replace(',', ' ').split()
        if choices == ['0']:
            return
        if choices and all(choice in ('1', '2', '3') for choice in choices):
            break
        print('请选择节点编号 1、2、3，可多选；输入 0 取消，不会默认安装全部。')
    protocols = [protocol for number, protocol in (('1', 'reality'), ('2', 'hysteria2'), ('3', 'cloudflare_ws'))
                 if number in choices]
    engine.version()
    if 'reality' in protocols:
        from sbmanager.system.network import public_addresses
        addresses = public_addresses()
        default_host = addresses.get('ipv4') or addresses.get('ipv6', '')
        public_host = host(ask(f'VPS 公网 IP 或域名（默认 {default_host}）' if default_host else 'VPS 公网 IP 或域名') or default_host)
    name = text(ask('首个用户名（默认 default）') or 'default', '用户名')
    domains = {}
    if 'reality' in protocols:
        handshake, domains['reality'] = ask_reality_names(ask)
        print(check_reality_target(handshake, domains['reality']))
    if 'hysteria2' in protocols:
        domains['hysteria2'] = host(ask('Hysteria2 证书域名（需指向本机）'))
    if 'cloudflare_ws' in protocols:
        domains['cloudflare_ws'] = host(ask('WebSocket 证书域名'))
        ws_path = websocket_path(ask('WebSocket 路径（回车自动生成）'))
    for protocol in protocols:
        if protocol == 'reality':
            continue
        domain = domains[protocol]
        try:
            socket.getaddrinfo(domain, 80)
        except OSError:
            raise ValidationError(f'找不到域名 {domain} 对应的 IP。请检查域名拼写和 DNS 记录，等待解析生效后重试') from None
    if any(protocol != 'reality' for protocol in protocols):
        print('证书验证需要公网 TCP 80 可达；请放行防火墙和安全组。\n'
              '使用 Cloudflare 时，验证请求也必须转发到本机；DNS 解析成功不代表端口可达。')
    nodes = []
    for protocol in protocols:
        domain = domains[protocol]
        settings = {**ask_inbound_ports(ask, protocol), 'server_name': domain,
                    'public_host': public_host if protocol == 'reality' else domain}
        if protocol == 'reality':
            private, public = engine.keypair()
            settings.update(private_key=private, public_key=public, short_id=secrets.token_hex(8), handshake=handshake)
        elif protocol == 'cloudflare_ws':
            settings['path'] = ws_path
        nodes.append({'id': identifier(), 'name': protocol.upper(), 'protocol': protocol, 'settings': settings})
    if ask('保存并创建节点和用户？（yes 确认，其他取消）') != 'yes':
        return
    def initialize(current):
        if current['inbounds'] or current['users']:
            raise ValidationError('其他操作已添加用户或节点，本次未保存。请返回菜单查看')
        current['inbounds'] = {node['id']: node for node in nodes}
        uid = identifier()
        current['users'][uid] = {'id': uid, 'name': name, 'enabled': True,
            'grants': {node['id']: credential(node['protocol']) for node in nodes}}
    manager.store.update(initialize)
    if 'cloudflare_ws' in protocols:
        print('WebSocket 路径:', ws_path)
    print('首次设置已保存。\n'
          '下一步：服务管理 > 检查配置并启动服务、检查证书；用户管理 > 导出客户端配置。\n'
          '请用客户端测试连接；本地模式不会启动服务。')
