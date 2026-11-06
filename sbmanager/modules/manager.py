"""Business state operations, independent of service deployment."""
from sbmanager.security import ValidationError, text, identifier, credential
from sbmanager.egress.registry import driver

PROTOCOLS = ('reality', 'hysteria2', 'cloudflare_ws')


def require(mapping, key, label):
    if key not in mapping:
        raise ValidationError(f'{label}不存在')
    return mapping[key]


class Manager:
    def __init__(self, store):
        self.store = store

    def add_inbound(self, name, protocol):
        if protocol not in PROTOCOLS:
            raise ValidationError('不支持的入站协议')
        entry = {'id': identifier(), 'name': text(name, '名称'), 'protocol': protocol}
        def change(state):
            state['inbounds'][entry['id']] = entry
            return entry['id']
        return self.store.update(change)

    def add_user(self, name):
        name = text(name, '用户名')
        def change(state):
            if any(u['name'] == name for u in state['users'].values()):
                raise ValidationError('用户名已存在')
            key = identifier()
            state['users'][key] = {'id': key, 'name': name, 'enabled': True, 'grants': {}}
            return key
        return self.store.update(change)

    def grant(self, user_id, inbound_id):
        def change(state):
            user = require(state['users'], user_id, '用户')
            inbound = require(state['inbounds'], inbound_id, '入站')
            if inbound_id in user['grants']:
                raise ValidationError('授权已存在')
            user['grants'][inbound_id] = credential(inbound['protocol'])
        self.store.update(change)

    def reset_credential(self, user_id, inbound_id):
        def change(state):
            user = require(state['users'], user_id, '用户')
            require(user['grants'], inbound_id, '授权')
            inbound = require(state['inbounds'], inbound_id, '入站')
            user['grants'][inbound_id] = credential(inbound['protocol'])
        self.store.update(change)

    def set_enabled(self, user_id, enabled):
        if type(enabled) is not bool:
            raise ValidationError('启用状态必须是布尔值')
        def change(state):
            require(state['users'], user_id, '用户')['enabled'] = enabled
        self.store.update(change)

    def revoke(self, user_id, inbound_id):
        def change(state):
            grants = require(state['users'], user_id, '用户')['grants']
            require(grants, inbound_id, '授权')
            del grants[inbound_id]
            state['bindings'].pop(f'{user_id}:{inbound_id}', None)
        self.store.update(change)

    def delete_user(self, user_id):
        def change(state):
            require(state['users'], user_id, '用户')
            del state['users'][user_id]
            state['bindings'] = {k: v for k, v in state['bindings'].items() if v['user_id'] != user_id}
        self.store.update(change)

    def save_egress(self, name, protocol, values, egress_id=None):
        profile = driver(protocol).validate(values)
        name = text(name, '出口名称')
        def change(state):
            key = egress_id or identifier()
            if egress_id:
                require(state['egress'], key, '出口')
            state['egress'][key] = {'id': key, 'name': name, 'protocol': protocol, 'settings': profile}
            return key
        return self.store.update(change)

    def delete_egress(self, egress_id):
        def change(state):
            require(state['egress'], egress_id, '出口')
            if any(egress_id in b['saved'] for b in state['bindings'].values()):
                raise ValidationError('出口仍被引用，请先解除绑定')
            del state['egress'][egress_id]
        self.store.update(change)

    def bind(self, user_id, inbound_id, egress_id=None):
        def change(state):
            user = require(state['users'], user_id, '用户')
            require(user['grants'], inbound_id, '授权')
            if egress_id is not None:
                require(state['egress'], egress_id, '出口')
            key = f'{user_id}:{inbound_id}'
            binding = state['bindings'].setdefault(key, {'user_id': user_id, 'inbound_id': inbound_id, 'saved': [], 'active': None})
            if egress_id is not None and egress_id not in binding['saved']:
                binding['saved'].append(egress_id)
            binding['active'] = egress_id
        self.store.update(change)

    def unbind(self, user_id, inbound_id, egress_id):
        def change(state):
            binding = require(state['bindings'], f'{user_id}:{inbound_id}', '绑定')
            if egress_id not in binding['saved']:
                raise ValidationError('该出口未绑定')
            if binding['active'] == egress_id:
                raise ValidationError('请先明确选择 DIRECT 或其他出口，再解除当前出口绑定')
            binding['saved'].remove(egress_id)
        self.store.update(change)

    def summary(self):
        state = self.store.read()
        for user in state['users'].values():
            user['grants'] = list(user['grants'])
        for inbound in state['inbounds'].values():
            if 'private_key' in inbound.get('settings', {}):
                inbound['settings']['private_key'] = '***'
        for profile in state['egress'].values():
            profile['settings']['password'] = '***'
        return state
