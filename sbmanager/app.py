import argparse
import os
import platform
from sbmanager.system.singbox import SingBox
from sbmanager.system.systemd import Systemd
from sbmanager.core.transaction_manager import Deployment
from pathlib import Path
from sbmanager.core.state_manager import StateStore
from sbmanager.modules.manager import Manager
from sbmanager.cli import run


def main():
    parser = argparse.ArgumentParser(description='Sing-Box Manager：管理节点、用户和出口；默认只在本地保存设置，不操作系统服务')
    parser.add_argument('--state-dir', type=Path, default=Path.home() / '.local/state/sbmanager-dev', help='本地模式保存设置的目录，含连接密钥，请勿公开')
    parser.add_argument('--system', action='store_true', help='管理 Linux 系统服务，需要 root 权限；安装后使用 sudo sbmanager 即可')
    parser.add_argument('--sing-box', default='sing-box', help='sing-box 程序的文件路径，默认从系统命令中查找')
    args = parser.parse_args()
    try:
        if args.system and (platform.system() != 'Linux' or os.geteuid() != 0):
            raise ValueError('管理系统服务需要 Linux 和 root 权限。请在已安装本工具的 Linux VPS 上运行 sudo sbmanager')
        directory = Path('/var/lib/sbmanager') if args.system else args.state_dir
        store = StateStore(directory)
        engine = SingBox(args.sing_box)
        deployment = None
        if args.system:
            deployment = Deployment(store, '/etc/sbmanager/config.json', engine, Systemd())
            store.deployment = deployment
            if not store.read().get('inbounds'):
                from sbmanager.modules.initialization import wizard
                from sbmanager.cli import ask
                wizard(Manager(store), engine, ask)
        return run(Manager(store), engine, deployment)
    except (OSError, ValueError) as error:
        parser.exit(1, f'启动失败: {error}\n')
