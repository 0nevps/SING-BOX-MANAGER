"""Business state operations, independent of service deployment."""
from sbmanager.security import ValidationError, text, identifier, credential
from sbmanager.egress.registry import driver

PROTOCOLS = ('reality', 'hysteria2', 'cloudflare_ws')


def require(mapping, key, label):
    if key not in mapping:
        raise ValidationError(f'找不到指定的{label}。请在菜单 1 查看当前设置，并复制正确的 ID')
    return mapping[key]


class Manager:
    def __init__(self, store):
        self.store = store

    def add_inbound(self, name, protocol):
        if protocol not in PROTOCOLS:
            raise ValidationError('节点协议不支持。请输入 reality、hysteria2 或 cloudflare_ws')
        entry = {'id': identifier(), 'name': text(name, '节点名称'), 'protocol': protocol}
        def change(state):
            state['inbounds'][entry['id']] = entry
            return entry['id']
        return self.store.update(change)

    def add_user(self, name):
        name = text(name, '用户名')
        def change(state):
            if any(u['name'] == name for u in state['users'].values()):
                raise ValidationError('这个用户名已存在，请换一个名称')
            key = identifier()
            state['users'][key] = {'id': key, 'name': name, 'enabled': True, 'grants': {}}
            return key
        return self.store.update(change)

    def grant(self, user_id, inbound_id):
        def change(state):
            user = require(state['users'], user_id, '用户')
            inbound = require(state['inbounds'], inbound_id, '节点')
            if inbound_id in user['grants']:
                raise ValidationError('这个用户已经可以使用该节点，无需重复开通')
            user['grants'][inbound_id] = credential(inbound['protocol'])
        self.store.update(change)

    def reset_credential(self, user_id, inbound_id):
        def change(state):
            user = require(state['users'], user_id, '用户')
            require(user['grants'], inbound_id, '节点使用权限')
            inbound = require(state['inbounds'], inbound_id, '节点')
            user['grants'][inbound_id] = credential(inbound['protocol'])
        self.store.update(change)

    def set_enabled(self, user_id, enabled):
        if type(enabled) is not bool:
            raise ValidationError('用户的启用设置格式不正确，必须为 true（启用）或 false（停用）')
        def change(state):
            require(state['users'], user_id, '用户')['enabled'] = enabled
        self.store.update(change)

    def revoke(self, user_id, inbound_id):
        def change(state):
            grants = require(state['users'], user_id, '用户')['grants']
            require(grants, inbound_id, '节点使用权限')
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
                raise ValidationError('还有用户保存了这个出口，暂时不能删除。请先在菜单 6 切换到其他出口或直连，再在菜单 12 移除它')
            del state['egress'][egress_id]
        self.store.update(change)

    def bind(self, user_id, inbound_id, egress_id=None):
        def change(state):
            user = require(state['users'], user_id, '用户')
            require(user['grants'], inbound_id, '节点使用权限')
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
            binding = require(state['bindings'], f'{user_id}:{inbound_id}', '用户节点出口设置')
            if egress_id not in binding['saved']:
                raise ValidationError('这个用户在指定节点上没有保存该出口，请检查用户、节点和出口 ID')
            if binding['active'] == egress_id:
                raise ValidationError('这个出口正在使用，不能直接移除。请先在菜单 6 切换到其他出口，或将出口 ID 留空改为直连（DIRECT），再重试')
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
