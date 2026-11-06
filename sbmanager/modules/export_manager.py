"""Per-user client configuration and sharing links; never export another user's secrets."""
from urllib.parse import urlencode, quote
from sbmanager.security import ValidationError


def export_user(state, user_id, inbound_id=None):
    user = state['users'].get(user_id)
    if not user or not user['enabled']:
        raise ValidationError('找不到用户，或该用户已停用。请在“用户管理 > 启用或停用”核对并启用用户，再到“导出客户端配置”重试')
    outbounds, links = [], []
    for iid, secret in user['grants'].items():
        if inbound_id is not None and iid != inbound_id:
            continue
        inbound = state['inbounds'][iid]
        settings = inbound.get('settings')
        if not settings:
            raise ValidationError('节点尚未配置完整，请到“节点管理 > 修改节点”完成设置')
        protocol = inbound['protocol']
        host = settings['public_host']
        port = settings.get('public_port', settings['port'])
        tls = {'enabled': True, 'server_name': settings['server_name']}
        node = {'type': 'hysteria2' if protocol == 'hysteria2' else 'vless',
                'tag': iid, 'server': host, 'server_port': port, 'tls': tls}
        params = {'sni': settings['server_name']}
        if protocol == 'hysteria2':
            node['password'] = secret
            scheme = 'hysteria2'
        else:
            node['uuid'] = secret
            scheme = 'vless'
            params.update({'encryption': 'none', 'security': 'tls', 'type': 'ws' if protocol == 'cloudflare_ws' else 'tcp'})
            if protocol == 'reality':
                node['flow'] = 'xtls-rprx-vision'
                tls.update({'utls': {'enabled': True, 'fingerprint': 'chrome'},
                            'reality': {'enabled': True, 'public_key': settings['public_key'], 'short_id': settings['short_id']}})
                params.update({'security': 'reality', 'pbk': settings['public_key'],
                               'sid': settings['short_id'], 'fp': 'chrome', 'flow': node['flow']})
            else:
                node['transport'] = {'type': 'ws', 'path': settings['path'], 'headers': {'Host': settings['server_name']}}
                params.update({'path': settings['path'], 'host': settings['server_name']})
        outbounds.append(node)
        address = f'[{host}]' if ':' in host else host
        links.append(f'{scheme}://{quote(secret, safe="")}@{address}:{port}?{urlencode(params)}#{quote(inbound["name"], safe="")}')
    if not outbounds:
        raise ValidationError('这个用户还不能使用任何节点。请先到“用户管理 > 开通节点”授权，再导出')
    return {'links': links, 'config': {'inbounds': [{'type': 'mixed', 'tag': 'local', 'listen': '127.0.0.1', 'listen_port': 2080}],
            'outbounds': [{'type': 'selector', 'tag': 'proxy', 'outbounds': [n['tag'] for n in outbounds]}] + outbounds,
            'route': {'final': 'proxy'}}}
