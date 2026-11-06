"""Interactive development CLI. No service is installed or changed."""
import getpass
import json
import subprocess
from pathlib import Path
from sbmanager.modules.node_manager import configure, ask_reality_names
from sbmanager.modules.export_manager import export_user
from sbmanager.modules.certificate_manager import inspect
from sbmanager.core.transaction_manager import atomic_write, encode
from sbmanager.egress.registry import driver
from sbmanager.modules.manager import PROTOCOLS


def ask(label):
    return input(label + ': ').strip()


def run(manager, engine=None, deployment=None):
    print('SING-BOX MANAGER — ' + ('系统管理模式' if deployment else '本地模式，不操作服务'))
    while True:
        print('\n1 查看状态  2 添加用户  3 添加入站档案  4 授权入站\n'
              '5 添加 SOCKS5 出口  6 切换出口  7 启用/禁用用户\n'
              '8 撤销授权  9 删除用户  10 删除出口  11 重置凭据  12 解除出口绑定\n'
              '13 配置入站  14 校验并部署  15 导出用户节点  16 测试出口  17 编辑出口\n'
              '18 服务状态  19 服务日志  20 证书状态  21 手动备份  22 列出备份\n'
              '23 恢复备份  24 设置备份保留数量  25 一键创建并授权全部入站  26 初始化向导  27 升级内核  0 退出')
        try:
            action = ask('请选择')
            if action == '0':
                return 0
            if action == '1':
                print(json.dumps(manager.summary(), ensure_ascii=False, indent=2))
            elif action == '2':
                print('用户 ID:', manager.add_user(ask('用户名')))
            elif action == '3':
                print('协议:', ', '.join(PROTOCOLS))
                print('入站 ID:', manager.add_inbound(ask('名称'), ask('协议')))
            elif action == '4':
                manager.grant(ask('用户 ID'), ask('入站 ID'))
            elif action == '5':
                name = ask('出口名称')
                settings = {'server': ask('服务器'), 'port': int(ask('端口')),
                            'username': ask('用户名'), 'password': getpass.getpass('密码: '),
                            'udp': ask('声明支持 UDP？输入 yes 确认') == 'yes'}
                print('出口 ID:', manager.save_egress(name, 'socks5', settings))
            elif action == '6':
                manager.bind(ask('用户 ID'), ask('入站 ID'), ask('出口 ID（留空明确选择 DIRECT）') or None)
            elif action == '7':
                uid = ask('用户 ID')
                choice = ask('启用输入 enable，禁用输入 disable')
                if choice not in ('enable', 'disable'):
                    raise ValueError('无效选择')
                manager.set_enabled(uid, choice == 'enable')
            elif action == '8':
                manager.revoke(ask('用户 ID'), ask('入站 ID'))
            elif action in ('9', '10'):
                key = ask('待删除 ID')
                if ask('确认删除？输入 yes') != 'yes':
                    continue
                (manager.delete_user if action == '9' else manager.delete_egress)(key)
            elif action == '11':
                manager.reset_credential(ask('用户 ID'), ask('入站 ID'))
            elif action == '12':
                manager.unbind(ask('用户 ID'), ask('入站 ID'), ask('出口 ID'))
            elif action == '13':
                iid = ask('入站 ID')
                inbound = manager.store.read()['inbounds'][iid]
                values = {'port': int(ask('源站监听端口')), 'public_port': int(ask('客户端连接端口')),
                          'public_host': ask('客户端连接 IP/域名')}
                if inbound['protocol'] == 'reality':
                    values['handshake'], values['server_name'] = ask_reality_names(ask)
                else:
                    values['server_name'] = ask('TLS Server Name/证书域名')
                    if inbound['protocol'] == 'cloudflare_ws':
                        values['path'] = ask('WebSocket 路径，例如 /gateway')
                configure(manager, engine, iid, values)
                if inbound['protocol'] == 'reality':
                    print('目标连通性、TLS 1.3 和证书域名校验通过；仍需 REALITY 客户端验证连接。')
            elif action == '14':
                if not deployment:
                    raise ValueError('部署需要已安装的 Linux 系统模式')
                def activate(state):
                    state['deployed'] = True
                manager.store.update(activate)
                print('配置已应用，服务和监听端口检查通过；客户端连通性仍需验证')
            elif action == '15':
                data = export_user(manager.store.read(), ask('用户 ID'))
                destination = Path(ask('导出目录（敏感数据，请勿提交）')).expanduser()
                if destination.exists():
                    raise ValueError('导出目录已存在，请使用新目录')
                destination.mkdir(parents=True, mode=0o700)
                atomic_write(destination / 'client.json', encode(data['config']))
                atomic_write(destination / 'links.txt', ('\n'.join(data['links']) + '\n').encode())
                print('导出完成，文件权限 0600')
            elif action in ('16', '17'):
                eid = ask('出口 ID')
                profile = manager.store.read()['egress'][eid]
                if action == '16':
                    print(driver(profile['protocol']).test_connection(profile))
                else:
                    settings = {'server': ask('服务器'), 'port': int(ask('端口')), 'username': ask('用户名'),
                                'password': getpass.getpass('密码: '), 'udp': ask('声明支持 UDP？输入 yes') == 'yes'}
                    manager.save_egress(ask('名称'), profile['protocol'], settings, eid)
            elif action in ('18', '19', '20', '21', '22', '23', '24'):
                if not deployment:
                    raise ValueError('此操作需要 Linux 系统模式')
                if action == '18':
                    print('运行中' if deployment.service.active() else '未运行')
                elif action == '19':
                    deployment.service.logs()
                elif action == '20':
                    print(json.dumps(inspect(manager.store.read(), manager.store.directory / 'acme'), ensure_ascii=False, indent=2))
                elif action == '22':
                    print('\n'.join(p.name for p in sorted(deployment.backups.glob('*.json'))))
                else:
                    with manager.store.locked():
                        if action == '21':
                            print('备份:', deployment.backup())
                        elif action == '23':
                            name = ask('备份名称')
                            if ask('恢复会替换当前状态和配置，输入 yes 确认') == 'yes':
                                deployment.restore(name)
                        else:
                            keep = int(ask('保留最近多少份备份（至少 1）'))
                            if keep < 1:
                                raise ValueError('至少保留一份备份')
                            state = manager.store._read()
                            state['backup_keep'] = keep
                            atomic_write(manager.store.path, encode(state))
                            deployment.prune(keep)
            elif action == '27':
                if not deployment:
                    raise ValueError('需要 Linux 系统模式')
                from sbmanager.system.kernel import upgrade
                version = ask('目标稳定版本，例如 1.14.4')
                if ask('确认升级内核？输入 yes') == 'yes':
                    upgrade(deployment, version)
            elif action == '26':
                from sbmanager.modules.initialization import wizard
                wizard(manager, engine, ask)
            elif action == '25':
                name = ask('用户名')
                from sbmanager.security import identifier, credential, text
                def create_all(state):
                    clean = text(name, '用户名')
                    if any(u['name'] == clean for u in state['users'].values()):
                        raise ValueError('用户名已存在')
                    if not state['inbounds']:
                        raise ValueError('请先创建入站')
                    uid = identifier()
                    state['users'][uid] = {'id': uid, 'name': clean, 'enabled': True,
                        'grants': {iid: credential(i['protocol']) for iid, i in state['inbounds'].items()}}
                    return uid
                print('用户 ID:', manager.store.update(create_all))
            else:
                print('无效选项')
                continue
            if action != '1':
                print('操作完成。' if deployment else '本地操作完成；尚未应用至 sing-box。')
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
            print(f'操作失败: {error}')
        except (EOFError, KeyboardInterrupt):
            print('\n已退出')
            return 0
