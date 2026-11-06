"""Reject malformed or inconsistent stored business state before it can be applied."""
from sbmanager.security import ValidationError


def validate_state(state):
    if not isinstance(state, dict) or type(state.get('schema_version')) is not int or state['schema_version'] != 1:
        raise ValidationError('不支持的状态 schema')
    if type(state.get('backup_keep', 20)) is not int or state.get('backup_keep', 20) < 1:
        raise ValidationError('备份保留数量必须为正整数')
    for name in ('users', 'inbounds', 'egress', 'bindings'):
        if not isinstance(state.get(name), dict):
            raise ValidationError(f'无效状态字段: {name}')
    try:
        names = set()
        for key, user in state['users'].items():
            if user['id'] != key or type(user['enabled']) is not bool or not isinstance(user['grants'], dict):
                raise ValueError()
            if not isinstance(user['name'], str) or not user['name'] or user['name'] in names:
                raise ValueError()
            names.add(user['name'])
            for iid, secret in user['grants'].items():
                if iid not in state['inbounds'] or not isinstance(secret, str) or not secret:
                    raise ValueError()
        for key, inbound in state['inbounds'].items():
            if inbound['id'] != key or inbound['protocol'] not in ('reality', 'hysteria2', 'cloudflare_ws'):
                raise ValueError()
        for key, profile in state['egress'].items():
            from sbmanager.egress.registry import driver
            if profile['id'] != key:
                raise ValueError()
            driver(profile['protocol']).validate(profile['settings'])
        for key, binding in state['bindings'].items():
            uid, iid = binding['user_id'], binding['inbound_id']
            if key != f'{uid}:{iid}' or iid not in state['users'][uid]['grants']:
                raise ValueError()
            saved = binding['saved']
            if not isinstance(saved, list) or len(saved) != len(set(saved)) or any(e not in state['egress'] for e in saved):
                raise ValueError()
            if binding['active'] is not None and binding['active'] not in saved:
                raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValidationError('业务状态结构或关联关系损坏；未修改文件') from None
