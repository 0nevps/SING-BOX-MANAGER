"""Interactive menus for local settings and installed service management."""
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path
from sbmanager.modules.node_manager import configure, ask_reality_names, ask_inbound_ports
from sbmanager.modules.export_manager import export_user
from sbmanager.modules.certificate_manager import inspect
from sbmanager.core.transaction_manager import atomic_write, encode
from sbmanager.egress.registry import driver


STYLES = {
    'title': '\033[1;36m',
    'section': '\033[1m',
    'accent': '\033[36m',
    'success': '\033[32m',
    'warning': '\033[33m',
    'error': '\033[31m',
}
PROTOCOL_LABELS = {'reality': 'REALITY', 'hysteria2': 'Hysteria2', 'cloudflare_ws': 'WebSocket'}
MENUS = (
    ('节点管理', ('查看节点', '添加节点', '设置地址和端口', '首次设置向导')),
    ('用户管理', ('查看用户', '添加用户', '添加用户并开通全部节点', '开通节点', '启用或停用',
                  '取消节点权限', '重置连接密钥', '删除用户', '导出客户端配置')),
    ('出口管理', ('查看出口', '添加 SOCKS5', '切换用户出口', '测试连接', '修改出口',
                  '移除已保存的出口', '删除出口')),
    ('服务管理', ('查看状态', '检查配置并启动服务', '查看日志', '检查证书', '升级 sing-box')),
    ('备份与恢复', ('创建备份', '查看备份', '从备份恢复', '设置保留数量')),
    ('高级与帮助', ('查看原始设置 JSON', '术语帮助')),
)
DANGEROUS = {'删除用户', '删除出口'}
CAUTION = {'取消节点权限', '重置连接密钥', '从备份恢复', '设置保留数量', '升级 sing-box'}


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


def choose(title, options, back='取消'):
    """Select a value by its visible number; zero never selects an object."""
    options = list(options)
    if not options:
        message('暂无可选项', tone='warning')
        raise Cancelled
    while True:
        print('\n' + styled(title, 'section'))
        for number, (_, label) in enumerate(options, 1):
            tone = 'error' if label in DANGEROUS else 'warning' if label in CAUTION else None
            line = f' {number} {label}'
            print(styled(line, tone) if tone else styled(f' {number}', 'accent') + ' ' + label)
        print('\n' + styled(f' 0 {back}', 'section'))
        answer = ask('请选择')
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
    return ask(warning + '\n输入 yes 确认，其他输入取消', tone='warning') == 'yes'


def show_records(manager, kind):
    state = manager.store.read()
    records = state[kind]
    if not records:
        message('暂无记录', tone='warning')
        return
    for number, record in enumerate(records.values(), 1):
        print('\n' + styled(f'{number}. {record["name"]}', 'section'))
        if kind == 'inbounds':
            settings = record.get('settings', {})
            print('  协议：' + PROTOCOL_LABELS[record['protocol']])
            print(f'  地址：{settings["public_host"]}:{settings.get("public_port", settings["port"])}' if settings else '  地址：未配置')
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
            print(f'  服务器：{settings["server"]}:{settings["port"]}')
            print('  UDP：' + ('声明支持，未验证' if settings['udp'] else '已阻止'))


def edit_node(manager, engine):
    state = manager.store.read()
    iid = select_record(state['inbounds'], '选择节点', 'inbounds')
    inbound = state['inbounds'][iid]
    values = {**ask_inbound_ports(ask, inbound['protocol'], inbound.get('settings')),
              'public_host': ask('公网 IP 或域名')}
    if inbound['protocol'] == 'reality':
        values['handshake'], values['server_name'] = ask_reality_names(ask)
    else:
        values['server_name'] = ask('证书域名')
        if inbound['protocol'] == 'cloudflare_ws':
            existing = inbound.get('settings', {}).get('path')
            values['path'] = ask(f'WebSocket 路径（回车保留 {existing}）' if existing else 'WebSocket 路径（回车自动生成）')
    configure(manager, engine, iid, values)
    message('节点已保存')
    if inbound['protocol'] == 'cloudflare_ws':
        print('WebSocket 路径：' + manager.store.read()['inbounds'][iid]['settings']['path'])
        message('路径变更后需重新导出客户端配置', tone='warning')


def node_action(action, manager, engine):
    if action == 1:
        show_records(manager, 'inbounds')
    elif action == 2:
        protocol = choose('选择协议', PROTOCOL_LABELS.items())
        manager.add_inbound(ask('节点名称'), protocol)
        message('节点已添加，请设置地址和端口')
    elif action == 3:
        edit_node(manager, engine)
    else:
        from sbmanager.modules.initialization import wizard
        wizard(manager, engine, ask)


def export_client(manager):
    state = manager.store.read()
    uid = select_record(state['users'], '选择用户', 'users')
    data = export_user(state, uid)
    message('导出文件含连接密钥，请勿公开', tone='warning')
    destination = Path(ask('保存到新目录')).expanduser()
    if destination.exists():
        raise ValueError('目录已存在，请换一个新目录')
    destination.mkdir(parents=True, mode=0o700)
    atomic_write(destination / 'client.json', encode(data['config']))
    atomic_write(destination / 'links.txt', ('\n'.join(data['links']) + '\n').encode())
    message('已导出 client.json 和 links.txt（权限 0600）')


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
    elif action == 9:
        export_client(manager)
    elif action in (4, 6, 7):
        uid, iid = user_node(manager, granted=action != 4)
        if action == 4:
            manager.grant(uid, iid)
            message('节点已开通')
        elif action == 6:
            if confirm('将取消此节点权限，并移除对应出口设置。'):
                manager.revoke(uid, iid)
                message('节点权限已取消')
        elif confirm('旧连接密钥将失效，需重新导出客户端配置。'):
            manager.reset_credential(uid, iid)
            message('连接密钥已重置')
    else:
        uid = select_record(manager.store.read()['users'], '选择用户', 'users')
        if action == 5:
            enabled = choose('用户状态', ((True, '启用'), (False, '停用（不能连接，保留设置）')))
            manager.set_enabled(uid, enabled)
            message('用户已启用' if enabled else '用户已停用')
        elif confirm('删除后无法直接撤销，全部节点权限和出口设置将被移除。'):
            manager.delete_user(uid)
            message('用户已删除')


def socks_settings():
    return {'server': ask('SOCKS5 服务器 IP 或域名'), 'port': int(ask('端口')),
            'username': ask('用户名'), 'password': getpass.getpass('密码（输入隐藏）\n> '),
            'udp': ask('支持 UDP？（yes 支持，回车阻止）') == 'yes'}


def egress_action(action, manager):
    if action == 1:
        show_records(manager, 'egress')
    elif action == 2:
        name = ask('出口名称')
        manager.save_egress(name, 'socks5', socks_settings())
        message('出口已添加')
    elif action in (3, 6):
        uid, iid = user_node(manager)
        state = manager.store.read()
        if action == 3:
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
        elif action == 5:
            name = ask('出口名称')
            manager.save_egress(name, profile['protocol'], socks_settings(), eid)
            message('出口已保存')
        elif confirm('删除出口后无法直接撤销。'):
            manager.delete_egress(eid)
            message('出口已删除')


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
    else:
        from sbmanager.system.kernel import upgrade
        version = ask('sing-box 版本（1.14.x，不加 v）')
        if confirm('将替换 sing-box 程序；运行中的服务会重启，连接可能短暂中断。'):
            upgrade(deployment, version)
            message('sing-box 已升级')


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


def advanced_action(action, manager):
    if action == 1:
        print(json.dumps(manager.summary(), ensure_ascii=False, indent=2))
    else:
        print('节点：客户端连接的入口。\n'
              '用户：独立的连接身份，可分配节点权限。\n'
              '出口：VPS 访问网络使用的线路；直连不经过代理。\n'
              '连接密钥：客户端认证信息，请勿公开。')


def run(manager, engine, deployment):
    print('\n' + styled('SING-BOX MANAGER', 'title'))
    section = None
    while True:
        try:
            if section is None:
                section = choose('主菜单', ((number, menu[0]) for number, menu in enumerate(MENUS, 1)), back='退出')
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
                service_action(action, manager, deployment)
            elif section == 5:
                backup_action(action, manager, deployment)
            else:
                advanced_action(action, manager)
        except Cancelled:
            if section is None:
                return 0
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
            message(f'操作未完成：{error}', tone='error')
        except (EOFError, KeyboardInterrupt):
            print('\n已退出')
            return 0
