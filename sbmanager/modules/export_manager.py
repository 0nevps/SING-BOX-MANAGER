"""Per-user client configuration and sharing links; never export another user's secrets."""
from urllib.parse import urlencode, quote
from sbmanager.security import ValidationError


def export_user(state, user_id):
    user = state['users'].get(user_id)
    if not user or not user['enabled']:
        raise ValidationError('只能导出已启用用户')
    outbounds, links = [], []
    for iid, secret in user['grants'].items():
        inbound = state['inbounds'][iid]
        settings = inbound.get('settings')
        if not settings:
            raise ValidationError('入站尚未配置部署参数')
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
        raise ValidationError('用户没有入站授权')
    return {'links': links, 'config': {'inbounds': [{'type': 'mixed', 'tag': 'local', 'listen': '127.0.0.1', 'listen_port': 2080}],
            'outbounds': [{'type': 'selector', 'tag': 'proxy', 'outbounds': [n['tag'] for n in outbounds]}] + outbounds,
            'route': {'final': 'proxy'}}}
