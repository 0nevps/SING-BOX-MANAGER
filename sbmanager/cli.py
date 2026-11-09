"""Interactive menus for local settings and installed service management."""
import json
import os
import platform
import shutil
import subprocess
import sys
import unicodedata
from sbmanager.modules.node_manager import configure, ask_inbound_ports, PROTOCOL_LABELS
from sbmanager.modules.export_manager import export_user
from sbmanager.modules.certificate_manager import inspect
from sbmanager.core.transaction_manager import atomic_write, encode
from sbmanager.core.forwarding import check_forward_conflict, validate_forward_listener
from sbmanager.security import PortInUse
from sbmanager.system.network import check_available
from sbmanager.egress.registry import driver
from sbmanager.egress.links import parse_link
from sbmanager.system import bbr


STYLES = {
    'title': '\033[1;32m',
    'section': '\033[32m',
    'accent': '\033[32m',
    'info': '\033[34m',
    'success': '\033[32m',
    'warning': '\033[33m',
    'error': '\033[31m',
}
MENUS = (
    ('节点管理', ('查看节点', '添加节点', '修改节点', '删除节点')),
    ('用户管理', ('查看用户', '添加用户', '添加用户并开通全部节点', '启用或停用用户', '开通节点',
                  '取消节点权限', '重置连接密钥', '删除用户')),
    ('出口管理', ('查看出口', '添加出口', '修改出口', '测试连接', '切换用户出口',
                  '移除已保存的出口', '删除出口')),
    ('端口转发', ('查看转发', '添加转发', '编辑转发', '删除转发')),
    ('服务管理', ('查看状态', '检查配置并启动服务', '查看日志', '检查证书', '查看原始设置 JSON')),
    ('备份与恢复', ('创建备份', '查看备份', '从备份恢复', '设置保留数量')),
    ('网络设置', ('节点流量仅用 IPv4', '开启 BBR')),
    ('更新与卸载', ('更新管理程序', '升级 sing-box', '卸载全部')),
)
DANGEROUS = {'删除节点', '删除用户', '删除出口', '删除转发', '卸载全部'}
CAUTION = {'取消节点权限', '重置连接密钥', '从备份恢复', '设置保留数量', '升级 sing-box', '更新管理程序', '开启 BBR'}


class Cancelled(Exception):
    """Return to the current menu without applying changes."""


def styled(text, tone):
    """Use terminal colors only when output supports them and the user allows it."""
    if not sys.stdout.isatty() or 'NO_COLOR' in os.environ or os.environ.get('TERM') == 'dumb':
        return text
    return STYLES[tone] + text + '\033[0m'


def message(*parts, tone='success'):
    print(styled(' '.join(str(part) for part in parts), tone))


def ask(label, tone='accent'):
    return input(styled(label, tone) + '\n' + styled('> ', 'accent')).strip()


def menu_width():
    """Leave one terminal column free to avoid automatic wrapping of rules."""
    return max(1, min(56, shutil.get_terminal_size(fallback=(80, 24)).columns - 1))


def display_width(text):
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in 'WF' else 1 for char in text)


def menu_text(text, prefix='  ', tone=None, prefix_tone=None, continuation=None):
    """Wrap plain text before coloring so ANSI codes never affect alignment."""
    width = menu_width()
    indent = ' ' * display_width(prefix) if continuation is None else continuation
    line = ''
    cells = display_width(prefix)
    for char in text:
        size = display_width(char)
        if cells + size > width and line:
            print((styled(prefix, prefix_tone) if prefix_tone else prefix)
                  + (styled(line, tone) if tone else line))
            prefix = indent
            line = ''
            cells = display_width(prefix)
        line += char
        cells += size
    print((styled(prefix, prefix_tone) if prefix_tone else prefix)
          + (styled(line, tone) if tone else line))


def menu_rule():
    print(styled('=' * menu_width(), 'accent'))


def menu_heading(title):
    print()
    menu_rule()
    heading = 'SING-BOX MANAGER · 主菜单' if title == '主菜单' else title
    padding = max(0, (menu_width() - display_width(heading)) // 2)
    menu_text(heading, prefix=' ' * padding, tone='title', continuation='  ')
    menu_rule()
    print()


def menu_field(label, value, tone='info'):
    menu_text(str(value), prefix=f'  {label}：', tone=tone,
              prefix_tone='accent', continuation='    ')


# Keep grouping on the main menu; submenus remain short numbered lists.
MENU_GROUPS = {
    '主菜单': {1: '业务配置', 5: '运行与维护', 7: '系统设置'},
}


def main_status(deployment):
    """Refresh live status without loading or mutating business state."""
    for label, read in (('主机名', platform.node), ('系统', platform.release),
                        ('发行版', lambda: platform.freedesktop_os_release().get('PRETTY_NAME', '未知'))):
        try:
            value = read()
        except (OSError, ValueError):
            value = '未知（读取失败）'
        menu_field(label, value or '未知')
    print()
    try:
        active = deployment.service.active()
        service = '运行中' if active else '未运行'
        service_tone = 'success' if active else 'error'
    except (OSError, ValueError, subprocess.SubprocessError):
        service, service_tone = '未知（读取失败）', 'warning'
    try:
        active = bbr.enabled()
        congestion = '已开启' if active else '未开启'
        bbr_tone = 'success' if active else 'warning'
    except (OSError, ValueError):
        congestion, bbr_tone = '未知（读取失败）', 'warning'
    menu_field('BBR', congestion, tone=bbr_tone)
    menu_field('sing-box 服务', service, tone=service_tone)
    print()
    menu_rule()
    print()


def choose(title, options, back='取消', status=None):
    """Select a value by its visible number; zero never selects an object."""
    options = list(options)
    if not options:
        message('暂无可选项', tone='warning')
        raise Cancelled
    while True:
        menu_heading(title)
        if status is not None:
            status()
        menu_text('请选择操作：', tone='accent')
        groups = MENU_GROUPS.get(title, {}) if back != '取消' else {}
        for number, (_, label) in enumerate(options, 1):
            if number in groups:
                print()
                menu_text(f'[{groups[number]}]', tone='section')
            tone = 'error' if label in DANGEROUS else 'warning' if label in CAUTION else 'accent'
            menu_text(label, prefix=f'  {number:>2}) ', tone=tone,
                      prefix_tone='info' if tone == 'accent' else tone)
        print()
        menu_text(back, prefix='   0) ', tone='accent', prefix_tone='warning')
        print()
        answer = input(styled(f'  请输入选项 [0-{len(options)}]: ', 'accent')).strip()
        if answer == '0':
            raise Cancelled
        if answer.isascii() and answer.isdecimal() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        message('编号无效，请重新选择', tone='warning')


def select_record(records, title, kind):
    """Keep identifiers internal while disambiguating objects with useful details."""
    labels = []
    for key, record in records.items():
        detail = ''
        if kind == 'users':
            detail = '启用' if record['enabled'] else '停用'
        elif kind == 'inbounds':
            settings = record.get('settings', {})
            detail = PROTOCOL_LABELS[record['protocol']]
            detail += f' · {settings["public_host"]}:{settings.get("public_port", settings["port"])}' if settings else ' · 未配置'
        elif kind == 'egress':
            settings = record['settings']
            detail = f'{settings["server"]}:{settings["port"]}'
        labels.append((key, f'{record["name"]} · {detail}'))
    return choose(title, labels)


def user_node(manager, granted=True):
    state = manager.store.read()
    uid = select_record(state['users'], '选择用户', 'users')
    grants = state['users'][uid]['grants']
    nodes = {key: node for key, node in state['inbounds'].items() if (key in grants) == granted}
    iid = select_record(nodes, '选择节点', 'inbounds')
    return uid, iid


def confirm(warning):
    return ask(warning + '\n确认？[y/N]', tone='warning').lower() == 'y'


def show_records(manager, kind):
    state = manager.store.read()
    records = state[kind]
    if not records:
        message('暂无记录', tone='warning')
        return
    menu_heading({'inbounds': '节点列表', 'users': '用户列表', 'egress': '出口列表'}[kind])
    for number, record in enumerate(records.values(), 1):
        if number > 1:
            print(styled('-' * min(32, menu_width()), 'accent'))
        menu_text(f'{number}. {record["name"]}', tone='section')
        if kind == 'inbounds':
            settings = record.get('settings', {})
            print('  协议：' + PROTOCOL_LABELS[record['protocol']])
            print(f'  地址：{settings["public_host"]}:{settings.get("public_port", settings["port"])}' if settings else '  地址：未配置')
            if settings:
                print(f'  监听端口：{settings["port"]} · SNI：{settings.get("server_name", "—")}')
                for field, label in (('handshake', '握手目标'), ('path', 'WebSocket 路径'),
                                     ('connection_mode', '连接方式')):
                    if field in settings:
                        print(f'  {label}：{settings[field]}')
            users = [user for user in state['users'].values()
                     if user['enabled'] and record['id'] in user['grants']]
            if not settings:
                print('  分享链接：节点未配置完整')
            elif not users:
                print('  分享链接：无已启用的授权用户')
            else:
                message('  分享链接含连接密钥，请勿公开', tone='warning')
                for user in users:
                    print(f'  用户：{user["name"]}')
                    print(export_user(state, user['id'], record['id'])['links'][0])
        elif kind == 'users':
            message('  状态：' + ('启用' if record['enabled'] else '停用'),
                    tone='success' if record['enabled'] else 'warning')
            if not record['grants']:
                print('  节点：未开通')
            for iid in record['grants']:
                binding = state['bindings'].get(f'{record["id"]}:{iid}', {})
                active = binding.get('active')
                egress = state['egress'][active]['name'] if active else '直连'
                print(f'  节点：{state["inbounds"][iid]["name"]} · 出口：{egress}')
        else:
            settings = record['settings']
            print('  协议：' + record['protocol'].upper())
            print(f'  服务器：{settings["server"]}:{settings["port"]}')
            print('  UDP：' + ('声明支持，未验证' if settings['udp'] else '已阻止'))


def node_field(label, default=''):
    value = ask(label + (f' [{default}]' if default else ''))
    if value == '0':
        raise Cancelled
    return value or default


def edit_node(manager, engine, adding=False):
    nodes = manager.store.read()['inbounds']
    iid = None if adding else select_record(nodes, '选择节点', 'inbounds')
    inbound = nodes.get(iid, {})
    print('回车使用默认值，0 取消')
    if adding:
        protocol = choose('选择协议', PROTOCOL_LABELS.items())
        default = PROTOCOL_LABELS[protocol]
        names = {node['name'] for node in nodes.values()}
        number = 2
        while default in names:
            default = f'{PROTOCOL_LABELS[protocol]} {number}'
            number += 1
        name = node_field('节点名称', default)
    else:
        name = inbound['name']
        print('节点名称：' + name + '（不可修改）')
        protocol = inbound['protocol']
        print('协议：' + PROTOCOL_LABELS[protocol] + '（不可修改）')
    previous = inbound.get('settings', {}) if protocol == inbound.get('protocol') else {}
    values = {**previous, **ask_inbound_ports(node_field, protocol, previous),
              'public_host': node_field('公网 IP 或域名', previous.get('public_host', ''))}
    if protocol == 'reality':
        target = node_field('REALITY 目标网站域名', previous.get('server_name') or previous.get('handshake', ''))
        values['handshake'] = values['server_name'] = target
    else:
        values['server_name'] = node_field('证书域名', previous.get('server_name', values['public_host']))
        if protocol == 'cloudflare_ws':
            values['path'] = node_field('WebSocket 路径' if previous.get('path') else 'WebSocket 路径（留空自动生成）',
                                        previous.get('path', ''))
    iid = configure(manager, engine, iid, values, name=name, protocol=protocol)
    message('节点已添加' if adding else '节点已保存')
    if protocol == 'cloudflare_ws':
        settings = manager.store.read()['inbounds'][iid]['settings']
        print('WebSocket 路径：' + settings['path'])
        if settings.get('connection_mode') == 'cloudflare':
            print('\nCloudflare 配置（需手动设置，程序不会自动修改）：')
            print('保持橙云开启，在 Origin Rules（回源规则）中使用以下匹配表达式：')
            print(f'(http.host eq "{settings["server_name"]}" and not starts_with('
                  'http.request.uri.path, "/.well-known/acme-challenge/"))')
            print(f'Rewrite port（回源端口）：{settings["port"]}')
            print('证书验证路径 /.well-known/acme-challenge/ 不要强制跳转 HTTPS，'
                  '也不要被其他规则改写到节点端口。')
            print('请在 VPS 防火墙和云安全组长期允许公网 TCP 80 到达源站；'
                  '申请和自动续期均需要。')
            print('验证期间由 sing-box 临时监听 TCP 80，不要另开服务占用该端口。')


def node_action(action, manager, engine):
    if action == 1:
        show_records(manager, 'inbounds')
    elif action in (2, 3):
        edit_node(manager, engine, adding=action == 2)
    elif action == 4:
        state = manager.store.read()
        iid = select_record(state['inbounds'], '删除节点', 'inbounds')
        count = sum(iid in user['grants'] for user in state['users'].values())
        if confirm(f'删除节点「{state["inbounds"][iid]["name"]}」及 {count} 个用户的节点权限和对应出口绑定；旧连接失效。'):
            manager.delete_inbound(iid)
            message('节点已删除')


def user_action(action, manager):
    if action == 1:
        show_records(manager, 'users')
    elif action in (2, 3):
        name = ask('用户名')
        if action == 2:
            manager.add_user(name)
        else:
            manager.add_user_all(name)
        message('用户已添加' if action == 2 else '用户已添加，已开通全部节点')
    elif action in (5, 6, 7):
        uid, iid = user_node(manager, granted=action != 5)
        if action == 5:
            manager.grant(uid, iid)
            message('节点已开通')
        elif action == 6:
            if confirm('将取消此节点权限，并移除对应出口设置。'):
                manager.revoke(uid, iid)
                message('节点权限已取消')
        elif confirm('旧连接密钥将失效，请到“节点管理 > 查看节点”获取新分享链接并更新客户端。'):
            manager.reset_credential(uid, iid)
            message('连接密钥已重置')
    else:
        uid = select_record(manager.store.read()['users'], '选择用户', 'users')
        if action == 4:
            enabled = choose('用户状态', ((True, '启用'), (False, '停用（不能连接，保留设置）')))
            manager.set_enabled(uid, enabled)
            message('用户已启用' if enabled else '用户已停用')
        elif confirm('删除后无法直接撤销，全部节点权限和出口设置将被移除。'):
            manager.delete_user(uid)
            message('用户已删除')


def edit_egress(manager, profile=None):
    link = ask('节点分享链接（支持 http、socks5、ss；输入可见，含账号密码请勿公开；0 取消）')
    if link == '0':
        raise Cancelled
    protocol, settings, link_name = parse_link(link)
    default = link_name or (profile['name'] if profile else protocol.upper())
    name = ask(f'出口名称（回车使用 {default}）') or default
    if protocol != 'http':
        settings['udp'] = ask('支持 UDP？[y/N]').lower() == 'y'
    manager.save_egress(name, protocol, settings, profile['id'] if profile else None)


def egress_action(action, manager):
    if action == 1:
        show_records(manager, 'egress')
    elif action == 2:
        edit_egress(manager)
        message('出口已添加')
    elif action in (5, 6):
        uid, iid = user_node(manager)
        state = manager.store.read()
        if action == 5:
            options = [(None, '直连（DIRECT）')]
            options.extend((key, record['name'] + f' · {record["settings"]["server"]}:{record["settings"]["port"]}')
                           for key, record in state['egress'].items())
            eid = choose('选择出口', options)
            manager.bind(uid, iid, eid)
            message('出口已切换')
        else:
            saved = state['bindings'].get(f'{uid}:{iid}', {}).get('saved', [])
            profiles = {key: state['egress'][key] for key in saved}
            eid = select_record(profiles, '选择已保存的出口', 'egress')
            manager.unbind(uid, iid, eid)
            message('已移除保存的出口')
    else:
        state = manager.store.read()
        eid = select_record(state['egress'], '选择出口', 'egress')
        profile = state['egress'][eid]
        if action == 4:
            result = driver(profile['protocol']).test_connection(profile)
            message(result['note'], tone='warning')
        elif action == 3:
            edit_egress(manager, profile)
            message('出口已保存')
        elif confirm('删除出口后无法直接撤销。'):
            manager.delete_egress(eid)
            message('出口已删除')


def forward_action(action, manager):
    records = manager.store.read().get('forwards', {})
    if action == 1:
        if not records:
            message('暂无端口转发', tone='warning')
        for record in records.values():
            network = 'TCP + UDP' if record['network'] == 'both' else record['network'].upper()
            print(f'{record["name"]} · {network} · [{record["listen"]}]:{record["listen_port"]}'
                  f' 转发到 [{record["target"]}]:{record["target_port"]} · 直连')
    elif action in (2, 3):
        key, previous = None, {}
        if action == 3:
            key = choose('编辑转发', ((key, f'{r["name"]} · {r["network"]} · [{r["listen"]}]:{r["listen_port"]}')
                                        for key, r in records.items()))
            previous = records[key]
        print('回车保留当前值，0 取消。监听公网地址会开放转发端口；请自行配置防火墙。' if previous else
              '回车使用默认值，0 取消。监听公网地址会开放转发端口；请自行配置防火墙。')
        name = node_field('转发名称', previous.get('name', '端口转发'))
        listen = node_field('监听 IP', previous.get('listen', '0.0.0.0'))
        choice = node_field('协议：1 TCP + UDP，2 TCP，3 UDP',
                            {'both': '1', 'tcp': '2', 'udp': '3'}[previous.get('network', 'both')])
        if choice not in ('1', '2', '3'):
            raise ValueError('请选择 1、2 或 3')
        network = {'1': 'both', '2': 'tcp', '3': 'udp'}[choice]

        def check_listener(values):
            state = manager.store.read()
            current = state.get('forwards', {}).pop(key, None)
            check_forward_conflict(state, values)
            # Running listeners cannot be probed with bind(). Reused transports on
            # the same port are checked by the deployment's post-restart health check.
            networks = ('tcp', 'udp') if values['network'] == 'both' else (values['network'],)
            reused = ()
            deployment = manager.store.deployment
            if (current and state.get('deployed') and deployment and deployment.service.active()
                    and current['listen_port'] == values['listen_port']):
                reused = ('tcp', 'udp') if current['network'] == 'both' else (current['network'],)
            listeners = [{'type': 'direct', 'listen': values['listen'], 'listen_port': values['listen_port'],
                          'network': network} for network in networks if network not in reused]
            if listeners:
                check_available({'inbounds': listeners})

        target = None
        while True:
            port = int(node_field('监听端口', str(previous.get('listen_port', ''))))
            values = validate_forward_listener({'listen': listen, 'listen_port': port, 'network': network})
            try:
                check_listener(values)
            except PortInUse as error:
                message(f'{error}。请重新输入监听端口，输入 0 取消', tone='warning')
                continue
            if target is None:
                target = node_field('目标 IP 或域名', previous.get('target', ''))
                target_port = int(node_field('目标端口', str(previous.get('target_port', ''))))
            try:
                check_listener(values)
                entry = {'name': name, **values, 'target': target, 'target_port': target_port}
                if key is None:
                    manager.add_forward(entry)
                else:
                    manager.update_forward(key, entry)
                break
            except PortInUse as error:
                message(f'{error}。请重新输入监听端口，输入 0 取消', tone='warning')
        message('转发已保存；首次使用请到“服务管理”检查配置并启动服务')
    elif action == 4:
        key = choose('删除转发', ((key, f'{r["name"]} · {r["network"]} · [{r["listen"]}]:{r["listen_port"]}')
                                    for key, r in records.items()))
        if confirm(f'删除转发「{records[key]["name"]}」，对应端口将停止转发。'):
            manager.delete_forward(key)
            message('转发已删除')


def show_certificates(manager):
    result = inspect(manager.store.read(), manager.store.directory / 'acme')
    for domain in result['domains']:
        print('\n域名：' + domain['domain'])
        print('  解析：' + (domain.get('dns_error') or '、'.join(domain['addresses'])))
    for certificate in result['certificates']:
        print('\n证书：' + certificate['file'])
        print('  ' + certificate['error'] if 'error' in certificate else '  到期：' + str(certificate['expires']))
    if not result['domains'] and not result['certificates']:
        message('暂无证书记录', tone='warning')
    message('检查范围：DNS、本地证书', tone='warning')


def service_action(action, manager, deployment):
    if action == 1:
        active = deployment.service.active()
        message('服务运行中' if active else '服务未运行，请启动服务或查看日志',
                tone='success' if active else 'warning')
    elif action == 2:
        def activate(state):
            state['deployed'] = True
        manager.store.update(activate)
        message('配置已生效，服务和端口检查通过')
    elif action == 3:
        deployment.service.logs()
    elif action == 4:
        show_certificates(manager)
    elif action == 5:
        print(json.dumps(manager.summary(), ensure_ascii=False, indent=2))


def maintenance_action(action, manager, deployment):
    if action == 1:
        from sbmanager.system.maintenance import update
        message('将从安装来源仓库 main 获取最新安装脚本；保留数据和配置。'
                '安装器会确认更新，运行中的服务可能短暂中断。', tone='warning')
        update()
    elif action == 2:
        from sbmanager.system.kernel import upgrade
        version = ask('sing-box 版本（1.14.x，不加 v）')
        if confirm('将替换 sing-box 程序；运行中的服务会重启，连接可能短暂中断。'):
            upgrade(deployment, version)
            message('sing-box 已升级')
    elif action == 3:
        from sbmanager.system.maintenance import uninstall, uninstall_paths
        warning = ('卸载将停止并移除 sbmanager-sing-box.service，永久删除以下路径，'
                   '包括全部用户、节点、密钥、证书缓存、备份和 sbmanager 指令：\n'
                   + '\n'.join(str(path) for path in uninstall_paths())
                   + '\n无法撤销。手动导出到其他目录的文件和系统依赖不会删除。')
        if confirm(warning):
            uninstall()
            message('已卸载全部安装文件、数据、配置和 sbmanager 指令')
            return True


def backup_action(action, manager, deployment):
    if action in (2, 3):
        files = sorted(path.name for path in deployment.backups.glob('*.json'))
        if action == 2:
            print('\n'.join(files) if files else '暂无备份')
            return
        name = choose('选择备份', ((name, name) for name in files))
        if confirm('将替换当前用户、节点、出口和配置，并重启服务；当前设置会另存备份。'):
            with manager.store.locked():
                deployment.restore(name)
            message('备份已恢复')
    elif action == 1:
        with manager.store.locked():
            name = deployment.backup()
        message('已创建备份：', name)
    else:
        keep = int(ask('保留份数（至少 1）'))
        if keep < 1:
            raise ValueError('至少保留 1 份备份')
        if confirm(f'将保留最近 {keep} 份备份，多余旧备份会被删除。'):
            with manager.store.locked():
                state = manager.store._read()
                state['backup_keep'] = keep
                atomic_write(manager.store.path, encode(state))
                deployment.prune(keep)
            message('备份保留数量已更新')


def network_action(action, manager):
    if action == 1:
        state = manager.store.read()
        enabled = state.get('direct_ipv4_only', False)
        menu_text('当前状态：' + ('已开启' if enabled else '已关闭'))
        menu_text('开启后，使用 VPS 本机出口的所有节点仅通过 IPv4 访问网站和其他目标；'
                  '无法访问仅支持 IPv6 的目标。')
        menu_text('不修改服务器全局网络设置。')
        menu_text('不影响客户端通过 IPv6 连接节点，不影响端口转发；'
                  '使用代理出口的流量不受此设置控制。')
        selected = choose('节点流量仅用 IPv4', ((True, '开启'), (False, '关闭')))
        if selected == enabled:
            message('设置未改变')
            return
        status = '开启' if selected else '关闭'
        if confirm(f'将{status}“节点流量仅用 IPv4”。已部署时会检查配置并重启服务，连接可能短暂中断。'):
            manager.set_direct_ipv4_only(selected)
            message('节点流量仅用 IPv4已' + status)
            if not state.get('deployed'):
                message('设置已保存；首次使用请到“服务管理”检查配置并启动服务', tone='warning')
    elif action == 2:
        if confirm('将修改全机 TCP 默认拥塞控制为 BBR、默认队列为 fq，并写入 '
                   '/etc/sysctl.d/99-sbmanager-bbr.conf 持久保存；影响不只限于 sing-box。'
                   '不更换内核，不重启服务。'):
            bbr.enable()
            message('BBR 已开启，fq / bbr 运行参数已检查，重启配置已保存')


def run(manager, engine, deployment):
    section = None
    while True:
        try:
            if section is None:
                section = choose('主菜单', ((number, menu[0]) for number, menu in enumerate(MENUS, 1)),
                                 back='退出', status=lambda: main_status(deployment))
                continue
            title, labels = MENUS[section - 1]
            try:
                action = choose(title, enumerate(labels, 1), back='返回')
            except Cancelled:
                section = None
                continue
            if section == 1:
                node_action(action, manager, engine)
            elif section == 2:
                user_action(action, manager)
            elif section == 3:
                egress_action(action, manager)
            elif section == 4:
                forward_action(action, manager)
            elif section == 5:
                service_action(action, manager, deployment)
            elif section == 6:
                backup_action(action, manager, deployment)
            elif section == 7:
                network_action(action, manager)
            elif section == 8:
                if maintenance_action(action, manager, deployment):
                    return 0
        except Cancelled:
            if section is None:
                return 0
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
            message(f'操作未完成：{error}', tone='error')
        except (EOFError, KeyboardInterrupt):
            print('\n已退出')
            return 0
