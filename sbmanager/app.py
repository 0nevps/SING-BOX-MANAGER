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
    parser = argparse.ArgumentParser(description='Sing-Box Manager 业务基础预览（不应用服务配置）')
    parser.add_argument('--state-dir', type=Path, default=Path.home() / '.local/state/sbmanager-dev', help='业务预览状态目录，包含敏感数据')
    parser.add_argument('--system', action='store_true', help='Linux root 系统服务模式')
    parser.add_argument('--sing-box', default='sing-box', help='sing-box 二进制路径')
    args = parser.parse_args()
    try:
        if args.system and (platform.system() != 'Linux' or os.geteuid() != 0):
            raise ValueError('系统模式需要 Linux 和 root 权限')
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
