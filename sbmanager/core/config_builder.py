"""sing-box 1.14 server configuration generated exclusively from business state."""
from sbmanager.security import ValidationError


def build(state, acme_directory='/var/lib/sbmanager/acme'):
    config = {'log': {'level': 'warn', 'timestamp': True}, 'inbounds': [],
              'outbounds': [{'type': 'direct', 'tag': 'direct'}],
              'route': {'rules': [], 'final': 'direct'}}
    for key, profile in state['egress'].items():
        from sbmanager.egress.registry import driver
        config['outbounds'].append(driver(profile['protocol']).build_outbound(profile))
    domains = sorted({i['settings']['server_name'] for i in state['inbounds'].values()
                      if i['protocol'] != 'reality' and i.get('settings')})
    if domains:
        config['certificate_providers'] = [{'type': 'acme', 'tag': 'managed-acme', 'domain': domains,
            'data_directory': acme_directory, 'provider': 'letsencrypt', 'disable_tls_alpn_challenge': True}]
    ports = set()
    for key, inbound in state['inbounds'].items():
        settings = inbound.get('settings')
        if not settings:
            raise ValidationError(f'入站 {inbound["name"]} 尚未配置部署参数')
        protocol = inbound['protocol']
        port = settings.get('port')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValidationError('无效入站端口')
        transport = 'udp' if protocol == 'hysteria2' else 'tcp'
        if (transport, port) in ports:
            raise ValidationError('入站监听端口冲突')
        ports.add((transport, port))
        users = []
        for uid, user in state['users'].items():
            if not user['enabled'] or key not in user['grants']:
                continue
            secret = user['grants'][key]
            entry = {'name': uid}
            if protocol == 'hysteria2':
                entry['password'] = secret
            else:
                entry['uuid'] = secret
                if protocol == 'reality':
                    entry['flow'] = 'xtls-rprx-vision'
            users.append(entry)
            binding = state['bindings'].get(f'{uid}:{key}')
            target = binding['active'] if binding else None
            if target is not None:
                if target not in state['egress']:
                    raise ValidationError('绑定引用不存在的出口')
                if not state['egress'][target]['settings']['udp']:
                    config['route']['rules'].append({'inbound': [key], 'auth_user': [uid],
                                                    'network': 'udp', 'action': 'reject'})
                config['route']['rules'].append({'inbound': [key], 'auth_user': [uid],
                                                'action': 'route', 'outbound': target})
        tls = {'enabled': True, 'server_name': settings['server_name']}
        node = {'type': 'hysteria2' if protocol == 'hysteria2' else 'vless',
                'tag': key, 'listen': settings.get('listen', '::'), 'listen_port': port,
                'users': users, 'tls': tls}
        if protocol == 'reality':
            tls['reality'] = {'enabled': True, 'handshake': {'server': settings['handshake'],
                               'server_port': settings.get('handshake_port', 443)},
                              'private_key': settings['private_key'], 'short_id': [settings['short_id']]}
        else:
            tls['certificate_provider'] = 'managed-acme'
            if protocol == 'cloudflare_ws':
                node['transport'] = {'type': 'ws', 'path': settings['path']}
        config['inbounds'].append(node)
    if not config['inbounds']:
        raise ValidationError('至少配置一个入站')
    return config
