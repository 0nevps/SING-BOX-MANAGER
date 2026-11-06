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
        raise ValidationError('已有用户或节点，不能重复首次设置。请选菜单 13 修改节点；现有数据不会被覆盖')
    engine.version()
    print('首次设置会创建 REALITY、Hysteria2、WebSocket 三个节点和一个用户。节点是手机或电脑连接的入口，用户用于分配连接权限。请准备 VPS 公网 IP、REALITY 目标网站域名，以及用于申请证书的自有域名。')
    from sbmanager.system.network import public_addresses
    addresses = public_addresses()
    print('自动检测的公网地址（ipv4/ipv6 分别表示两种 IP 地址，可在下一步手动填写）:', addresses or '未检测到，请手动填写 VPS 公网 IP 或域名')
    default_host = addresses.get('ipv4') or addresses.get('ipv6', '')
    public_host = host(ask(f'VPS 公网 IP 或域名（回车使用检测结果 {default_host}；未检测到时必须填写）') or default_host)
    name = text(ask('首个用户名（默认 default）') or 'default', '用户名')
    handshake, server_name = ask_reality_names(ask)
    print(check_reality_target(handshake, server_name))
    hy_domain = host(ask('Hysteria2 的证书域名（填写你自己的域名，需指向这台 VPS）'))
    ws_domain = host(ask('WebSocket 的证书域名（填写你自己的域名；使用 Cloudflare 时还需设置转发到这台 VPS）'))
    ws_path = websocket_path(ask('WebSocket 路径（直接回车自动生成，无需自己编写）'))
    for domain in (hy_domain, ws_domain):
        try:
            socket.getaddrinfo(domain, 80)
        except OSError:
            raise ValidationError(f'找不到域名 {domain} 对应的 IP。请检查域名拼写和 DNS 记录，等待解析生效后重试') from None
    print('申请证书时，外网必须能通过域名访问这台 VPS 的 TCP 80 端口。请检查防火墙和云平台安全组；使用 Cloudflare 时也要让验证请求转发到 VPS。域名能解析不代表此端口能从外网访问。')
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
    if ask('保存以上设置并创建三个节点和首个用户？确认请输入 yes，其他输入取消') != 'yes':
        return
    def initialize(current):
        if current['inbounds'] or current['users']:
            raise ValidationError('其他操作已添加用户或节点，本次首次设置未保存。请选菜单 1 查看当前设置')
        current['inbounds'] = {node['id']: node for node in nodes}
        uid = identifier()
        current['users'][uid] = {'id': uid, 'name': name, 'enabled': True,
            'grants': {node['id']: credential(node['protocol']) for node in nodes}}
    manager.store.update(initialize)
    print('WebSocket 路径:', ws_path)
    print('首次设置已保存，但这不代表节点已经可用。在已安装本工具的 Linux VPS 上，选菜单 14“检查配置并启动服务”；再选菜单 20 检查证书、菜单 15 导出配置，并用手机或电脑测试连接。本地模式不会启动服务。')
