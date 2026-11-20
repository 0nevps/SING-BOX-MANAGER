import re

from sbmanager.security import PortInUse, ValidationError


def hop_range(settings):
    value = settings.get('hop_range')
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,4}-[1-9][0-9]{0,4}', value):
        raise ValidationError('UDP 跳跃范围格式应为 起始端口-结束端口，例如 20000-30000')
    start, end = map(int, value.split('-'))
    if not start < end <= 65535:
        raise ValidationError('UDP 跳跃范围需要两个递增的端口，最大为 65535')
    return start, end


def hopping_rules(state):
    ranges = {}
    listeners = []
    for key, node in state['inbounds'].items():
        settings = node.get('settings', {})
        if node['protocol'] == 'hysteria2' and 'port' in settings:
            listeners.append((key, settings['port']))
        if 'hop_range' not in settings:
            continue
        if node['protocol'] != 'hysteria2':
            raise ValidationError('仅 Hysteria2 节点支持 UDP 端口跳跃')
        start, end = hop_range(settings)
        port = settings.get('port')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValidationError('Hysteria2 监听端口必须是 1–65535 之间的整数')
        for other_start, other_end, _ in ranges.values():
            if start <= other_end and other_start <= end:
                raise PortInUse('Hysteria2 UDP 跳跃范围与其他节点重叠')
        ranges[key] = (start, end, port)
    for key, (start, end, _) in ranges.items():
        if any(other != key and start <= port <= end for other, port in listeners):
            raise PortInUse('UDP 跳跃范围与其他 Hysteria2 监听端口冲突')
    return list(ranges.values())
