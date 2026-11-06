"""Reject malformed or inconsistent stored business state before it can be applied."""
from sbmanager.security import ValidationError


def validate_state(state):
    if not isinstance(state, dict) or type(state.get('schema_version')) is not int or state['schema_version'] != 1:
        raise ValidationError('保存的数据格式版本不兼容，无法继续。请使用匹配的程序版本，不要手动修改数据文件')
    if type(state.get('backup_keep', 20)) is not int or state.get('backup_keep', 20) < 1:
        raise ValidationError('备份保留数量必须是至少为 1 的整数，请检查备份设置')
    for name in ('users', 'inbounds', 'egress', 'bindings'):
        if not isinstance(state.get(name), dict):
            raise ValidationError(f'保存的数据格式不正确（字段 {name}）。请保留原文件，使用有效备份恢复，不要手动删除数据')
    from sbmanager.core.forwarding import validate_forwards
    try:
        validate_forwards(state)
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
    except ValidationError:
        raise
    except (KeyError, TypeError, ValueError):
        raise ValidationError('保存的用户、节点或出口数据不完整，或对应关系不正确；未修改文件。请保留原文件，使用有效备份恢复') from None
