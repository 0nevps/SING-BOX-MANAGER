"""Validation and configuration for fixed-destination TCP/UDP forwarding."""
import ipaddress
from sbmanager.egress.drivers.common import endpoint
from sbmanager.security import PortInUse, ValidationError, text


def validate_forward_listener(values):
    """Validate listener fields before the destination has been entered."""
    try:
        listen = str(ipaddress.ip_address(values.get('listen', '0.0.0.0')))
    except ValueError:
        raise ValidationError('监听地址必须是本机 IP，例如 0.0.0.0、127.0.0.1 或 ::') from None
    port = values.get('listen_port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValidationError('监听端口必须是 1–65535 之间的整数')
    network = values.get('network', 'both')
    if network not in ('tcp', 'udp', 'both'):
        raise ValidationError('转发协议必须是 tcp、udp 或 both')
    return {'listen': listen, 'listen_port': port, 'network': network}


def validate_forward(values):
    name = text(values.get('name'), '转发名称')
    listener = validate_forward_listener(values)
    target = endpoint({'server': values.get('target'), 'port': values.get('target_port')})
    if target['server'] == listener['listen'] and target['port'] == listener['listen_port']:
        raise ValidationError('转发目标不能与监听地址和端口相同')
    return {'name': name, **listener, 'target': target['server'], 'target_port': target['port']}


def check_forward_conflict(state, values):
    """Check a proposed listener against all reserved transports and ports."""
    values = validate_forward_listener(values)
    occupied = set()
    for node in state['inbounds'].values():
        settings = node.get('settings', {})
        if settings:
            occupied.add(('udp' if node['protocol'] == 'hysteria2' else 'tcp', settings['port']))
            if node['protocol'] != 'reality':
                occupied.add(('tcp', 80))
    for entry in state.get('forwards', {}).values():
        networks = ('tcp', 'udp') if entry['network'] == 'both' else (entry['network'],)
        occupied.update((network, entry['listen_port']) for network in networks)
    networks = ('tcp', 'udp') if values['network'] == 'both' else (values['network'],)
    for network in networks:
        if (network, values['listen_port']) in occupied:
            raise PortInUse(f'端口转发与节点、其他转发或证书验证端口冲突：{network.upper()} [{values["listen"]}]:{values["listen_port"]}')


def validate_forwards(state):
    forwards = state.get('forwards', {})
    if not isinstance(forwards, dict):
        raise ValidationError('端口转发数据格式不正确')
    # Conservatively reserve each transport/port across addresses, including dual-stack binds.
    checked = {'inbounds': state['inbounds'], 'forwards': {}}
    for key, entry in forwards.items():
        if not isinstance(entry, dict) or entry.get('id') != key or not isinstance(key, str) or not key:
            raise ValidationError('端口转发记录不完整')
        values = validate_forward(entry)
        check_forward_conflict(checked, values)
        checked['forwards'][key] = values


def build_forwards(state):
    validate_forwards(state)
    result = []
    for key, entry in state.get('forwards', {}).items():
        entry = validate_forward(entry)
        node = {'type': 'direct', 'tag': 'forward-' + key, 'listen': entry['listen'],
                'listen_port': entry['listen_port'], 'override_address': entry['target'],
                'override_port': entry['target_port']}
        if entry['network'] != 'both':
            node['network'] = entry['network']
        result.append(node)
    return result
