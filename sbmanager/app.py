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
    parser = argparse.ArgumentParser(description='Sing-Box Manager：管理节点、用户、出口和系统服务，需要 Linux 和 root 权限')
    parser.add_argument('--sing-box', default='sing-box', help='sing-box 程序的文件路径，默认从系统命令中查找')
    args = parser.parse_args()
    try:
        if platform.system() != 'Linux' or os.geteuid() != 0:
            raise ValueError('管理系统服务需要 Linux 和 root 权限。请在已安装本工具的 Linux VPS 上运行 sudo sbmanager')
        store = StateStore(Path('/var/lib/sbmanager'))
        engine = SingBox(args.sing_box)
        deployment = Deployment(store, '/etc/sbmanager/config.json', engine, Systemd())
        store.deployment = deployment
        return run(Manager(store), engine, deployment)
    except (OSError, ValueError) as error:
        parser.exit(1, f'启动失败: {error}\n')
