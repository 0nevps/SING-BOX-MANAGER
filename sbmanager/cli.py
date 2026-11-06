"""Interactive CLI for local settings and installed service management."""
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
from sbmanager.modules.manager import PROTOCOLS


STYLES = {
    'title': '\033[1;36m',
    'section': '\033[1m',
    'accent': '\033[36m',
    'success': '\033[32m',
    'warning': '\033[33m',
    'error': '\033[31m',
}

MENU_SECTIONS = (
    ('常用操作', ((1, '查看当前设置'), (15, '导出客户端配置'), (26, '首次设置向导'))),
    ('用户与权限', ((2, '添加用户'), (4, '允许用户使用节点'), (25, '为用户开通全部节点'),
                   (7, '启用或停用用户'), (8, '取消用户的节点权限'), (11, '重置连接密钥'), (9, '删除用户'))),
    ('节点管理', ((3, '添加节点'), (13, '设置节点地址和端口'))),
    ('出口管理', ((5, '添加 SOCKS5 出口'), (6, '切换用户出口'), (16, '测试出口连接'),
                 (17, '修改出口'), (12, '移除已保存的出口'), (10, '删除出口'))),
    ('服务与证书', ((14, '检查配置并启动服务'), (18, '查看服务状态'), (19, '查看服务日志'),
                   (20, '检查证书'), (27, '升级 sing-box'))),
    ('备份管理', ((21, '创建备份'), (22, '查看备份列表'), (23, '从备份恢复'), (24, '设置备份保留数量'))),
)


def styled(text, tone):
    """Use terminal colors only when output supports them and the user allows it."""
    if not sys.stdout.isatty() or 'NO_COLOR' in os.environ or os.environ.get('TERM') == 'dumb':
        return text
    return STYLES[tone] + text + '\033[0m'


def message(*parts, tone='success'):
    print(styled(' '.join(str(part) for part in parts), tone))


def ask(label, tone='accent'):
    return input(styled(label, tone) + '\n' + styled('> ', 'accent')).strip()


def show_menu():
    print('\n节点是手机或电脑连接的入口；\n'
          '出口是 VPS 访问网络时使用的线路。\n'
          '需要填写 ID 时，先选 1，复制对应的 id。\n'
          'users 是用户，inbounds 是节点，egress 是出口。')
    for title, options in MENU_SECTIONS:
        print('\n' + styled(title, 'section'))
        for number, label in options:
            if number in (9, 10):
                print(styled(f' {number:2d} {label}', 'error'))
            elif number in (8, 11, 12, 23, 24, 27):
                print(styled(f' {number:2d} {label}', 'warning'))
            else:
                print(styled(f' {number:2d}', 'accent') + ' ' + label)
    print('\n' + styled('  0 退出', 'section') + '\n')


def run(manager, engine=None, deployment=None):
    print('\n' + styled('SING-BOX MANAGER', 'title'))
    message('服务器管理模式：首次启动服务后，修改设置会自动更新服务' if deployment
            else '本地测试模式：只保存设置，不启动或修改系统服务', tone='accent' if deployment else 'warning')
    while True:
        show_menu()
        try:
            action = ask('请输入菜单编号（0 退出）')
            if action == '0':
                return 0
            if action == '1':
                print(json.dumps(manager.summary(), ensure_ascii=False, indent=2))
            elif action == '2':
                message('已添加用户，用户 ID:', manager.add_user(ask('用户名（自己起一个名称）')))
            elif action == '3':
                message('协议填写说明：\n'
                        '  reality       REALITY\n'
                        '  hysteria2     Hysteria2\n'
                        '  cloudflare_ws WebSocket\n'
                        '可输入: ' + ', '.join(PROTOCOLS), tone='accent')
                message('已添加节点，节点 ID:', manager.add_inbound(ask('节点名称（自己起一个名称）'), ask('协议（输入上面对应的英文值）')))
            elif action == '4':
                manager.grant(ask('用户 ID（从菜单 1 复制）'), ask('允许使用的节点 ID（从菜单 1 复制）'))
            elif action == '5':
                name = ask('出口名称（自己起一个名称，例如日本代理）')
                settings = {'server': ask('SOCKS5 服务器 IP 或域名（不要加 http://）'), 'port': int(ask('SOCKS5 端口（1–65535）')),
                            'username': ask('SOCKS5 用户名（由代理服务商提供）'), 'password': getpass.getpass('SOCKS5 密码（输入时不显示）: '),
                            'udp': ask('代理服务商是否明确支持 UDP？支持请输入 yes；不支持或不确定请直接回车，UDP 将被阻止') == 'yes'}
                message('已添加出口，出口 ID:', manager.save_egress(name, 'socks5', settings))
            elif action == '6':
                manager.bind(ask('用户 ID（从菜单 1 复制）'), ask('节点 ID（只修改该用户在此节点上的出口）'), ask('出口 ID（直接回车使用直连 DIRECT，不经过代理出口）') or None)
            elif action == '7':
                uid = ask('用户 ID（从菜单 1 复制）')
                choice = ask('启用请输入 enable；停用请输入 disable（停用后不能连接，原设置保留）')
                if choice not in ('enable', 'disable'):
                    raise ValueError('请输入 enable（启用）或 disable（停用）')
                manager.set_enabled(uid, choice == 'enable')
            elif action == '8':
                manager.revoke(ask('用户 ID（此操作会取消指定节点的使用权限，并移除该节点的出口设置）'), ask('要取消权限的节点 ID'))
            elif action in ('9', '10'):
                key = ask('要删除的用户或出口 ID（从菜单 1 复制）')
                if ask('删除后无法直接撤销；删除用户还会移除其全部节点权限和出口设置。\n确认请输入 yes，其他输入取消', tone='error') != 'yes':
                    continue
                (manager.delete_user if action == '9' else manager.delete_egress)(key)
            elif action == '11':
                manager.reset_credential(ask('用户 ID（重置后该节点的旧连接密钥失效，需重新导出客户端配置）'), ask('要重置连接密钥的节点 ID'))
            elif action == '12':
                manager.unbind(ask('用户 ID（从菜单 1 复制）'), ask('节点 ID（从菜单 1 复制）'), ask('要移除的出口 ID（如正在使用，请先在菜单 6 切换出口）'))
            elif action == '13':
                iid = ask('要设置的节点 ID（从菜单 1 复制）')
                inbound = manager.store.read()['inbounds'][iid]
                values = {**ask_inbound_ports(ask, inbound['protocol'], inbound.get('settings')),
                          'public_host': ask('手机或电脑连接的公网 IP 或域名（不要加 http://）')}
                if inbound['protocol'] == 'reality':
                    values['handshake'], values['server_name'] = ask_reality_names(ask)
                else:
                    values['server_name'] = ask('此节点的证书域名（填写你自己的域名，需直接指向或经 Cloudflare 转发到这台 VPS）')
                    if inbound['protocol'] == 'cloudflare_ws':
                        existing_path = inbound.get('settings', {}).get('path')
                        hint = f'直接回车保留 {existing_path}' if existing_path else '直接回车自动生成'
                        values['path'] = ask(f'WebSocket 路径（例如 /proxy；{hint}）')
                configure(manager, engine, iid, values)
                if inbound['protocol'] == 'reality':
                    message('目标网站连接、TLS 1.3 和证书域名检查通过。')
                    message('仍需 REALITY 客户端实际连接测试。', tone='warning')
                elif inbound['protocol'] == 'cloudflare_ws':
                    message('WebSocket 路径（修改后需重新导出客户端配置）:',
                            manager.store.read()['inbounds'][iid]['settings']['path'], tone='warning')
            elif action == '14':
                if not deployment:
                    raise ValueError('本地模式不能启动服务。请在已安装本工具的 Linux VPS 上运行 sudo sbmanager')
                def activate(state):
                    state['deployed'] = True
                manager.store.update(activate)
                message('配置已生效，服务已运行，端口检查通过。')
                message('请再用手机或电脑测试连接；这些检查不代表节点一定可用', tone='warning')
            elif action == '15':
                data = export_user(manager.store.read(), ask('要导出的用户 ID（从菜单 1 复制）'))
                destination = Path(ask('保存文件的新目录（例如 ~/my-nodes；文件含连接密钥，请勿公开或提交到 Git）')).expanduser()
                if destination.exists():
                    raise ValueError('这个目录已存在。为避免覆盖文件，请换一个新目录')
                destination.mkdir(parents=True, mode=0o700)
                atomic_write(destination / 'client.json', encode(data['config']))
                atomic_write(destination / 'links.txt', ('\n'.join(data['links']) + '\n').encode())
                message('已导出 client.json（客户端配置）和 links.txt（分享链接）。\n'
                        '文件权限为 0600，仅当前系统用户可读写。')
                message('文件含连接密钥，请勿公开', tone='warning')
            elif action in ('16', '17'):
                eid = ask('出口 ID（从菜单 1 复制）')
                profile = manager.store.read()['egress'][eid]
                if action == '16':
                    print(driver(profile['protocol']).test_connection(profile))
                else:
                    settings = {'server': ask('SOCKS5 服务器 IP 或域名（不要加 http://）'), 'port': int(ask('SOCKS5 端口（1–65535）')), 'username': ask('SOCKS5 用户名（由代理服务商提供）'),
                                'password': getpass.getpass('SOCKS5 密码（输入时不显示）: '), 'udp': ask('代理服务商是否明确支持 UDP？支持请输入 yes；不支持或不确定请直接回车，UDP 将被阻止') == 'yes'}
                    manager.save_egress(ask('出口名称（自己起一个名称）'), profile['protocol'], settings, eid)
            elif action in ('18', '19', '20', '21', '22', '23', '24'):
                if not deployment:
                    raise ValueError('本地模式不支持此操作。请在已安装本工具的 Linux VPS 上运行 sudo sbmanager')
                if action == '18':
                    active = deployment.service.active()
                    message('服务正在运行；是否能正常连接还需用客户端测试' if active
                            else '服务未运行。首次使用请选菜单 14；启动失败请选菜单 19 查看日志',
                            tone='success' if active else 'warning')
                elif action == '19':
                    deployment.service.logs()
                elif action == '20':
                    print(json.dumps(inspect(manager.store.read(), manager.store.directory / 'acme'), ensure_ascii=False, indent=2))
                elif action == '22':
                    print('\n'.join(p.name for p in sorted(deployment.backups.glob('*.json'))))
                else:
                    with manager.store.locked():
                        if action == '21':
                            message('已创建备份，备份文件名:', deployment.backup())
                        elif action == '23':
                            name = ask('备份文件名（从菜单 22 复制完整的 .json 文件名）')
                            if ask('恢复会替换当前用户、节点、出口和配置，并重启服务；当前设置会另存备份。\n确认请输入 yes，其他输入取消', tone='warning') == 'yes':
                                deployment.restore(name)
                        else:
                            keep = int(ask('保留最近多少份备份（输入至少为 1 的整数，多余旧备份会被删除）'))
                            if keep < 1:
                                raise ValueError('至少要保留 1 份备份，请输入不小于 1 的整数')
                            state = manager.store._read()
                            state['backup_keep'] = keep
                            atomic_write(manager.store.path, encode(state))
                            deployment.prune(keep)
            elif action == '27':
                if not deployment:
                    raise ValueError('本地模式不能升级 sing-box。请在已安装本工具的 Linux VPS 上运行 sudo sbmanager')
                from sbmanager.system.kernel import upgrade
                version = ask('要安装的 sing-box 稳定版本（仅支持 1.14.x，例如 1.14.4，不要加 v）')
                if ask('升级会替换 sing-box 程序；服务正在运行时会重启，连接可能短暂中断。\n确认请输入 yes，其他输入取消', tone='warning') == 'yes':
                    upgrade(deployment, version)
            elif action == '26':
                from sbmanager.modules.initialization import wizard
                wizard(manager, engine, ask)
            elif action == '25':
                name = ask('新用户名（此操作会添加用户，并允许其使用所有已有节点）')
                from sbmanager.security import identifier, credential, text
                def create_all(state):
                    clean = text(name, '用户名')
                    if any(u['name'] == clean for u in state['users'].values()):
                        raise ValueError('这个用户名已存在，请换一个名称')
                    if not state['inbounds']:
                        raise ValueError('还没有节点。请先选菜单 3 添加节点，或选菜单 26 完成首次设置')
                    uid = identifier()
                    state['users'][uid] = {'id': uid, 'name': clean, 'enabled': True,
                        'grants': {iid: credential(i['protocol']) for iid, i in state['inbounds'].items()}}
                    return uid
                message('已添加用户并开通全部节点，用户 ID:', manager.store.update(create_all))
            else:
                message('没有这个菜单选项，请输入 0–27 之间的编号', tone='warning')
                continue
            if action != '1':
                message('本次操作已结束；如有修改，结果以上方提示为准。' if deployment
                        else '本次本地操作已结束；设置尚未应用至 sing-box，不会启动或修改系统服务。', tone='warning')
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
            message(f'操作未完成，请检查输入、ID 或运行环境。\n错误详情: {error}', tone='error')
        except (EOFError, KeyboardInterrupt):
            print('\n已退出管理菜单')
            return 0
