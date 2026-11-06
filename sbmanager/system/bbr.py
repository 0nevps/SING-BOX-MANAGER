"""Enable the running kernel's BBR without replacing kernels or other sysctl files."""
import os
from pathlib import Path
import shutil
import stat
import subprocess

from sbmanager.core.transaction_manager import atomic_write
from sbmanager.security import ValidationError
from sbmanager.system.maintenance import INSTALL_LOCK, exclusive_lock


SYSCTL_ROOT = Path('/proc/sys')
CONFIG_PATH = Path('/etc/sysctl.d/99-sbmanager-bbr.conf')
CONGESTION = 'net.ipv4.tcp_congestion_control'
QDISC = 'net.core.default_qdisc'
AVAILABLE = 'net.ipv4.tcp_available_congestion_control'
CONFIG = f'{QDISC} = fq\n{CONGESTION} = bbr\n'.encode()


def _read(key):
    return SYSCTL_ROOT.joinpath(*key.split('.')).read_text().strip()


def enabled():
    """Report the live TCP default, not whether a configuration file exists."""
    return _read(CONGESTION) == 'bbr'


def _set(key, value):
    subprocess.run(['sysctl', '-w', f'{key}={value}'],
                   check=True, capture_output=True, timeout=10)


def enable():
    """Apply only our two settings; restore runtime and our file on failure."""
    with exclusive_lock(INSTALL_LOCK):
        if CONFIG_PATH.is_symlink():
            raise ValidationError(f'BBR 配置是符号链接，已停止写入：{CONFIG_PATH}')
        previous_file = CONFIG_PATH.read_bytes() if CONFIG_PATH.exists() else None
        previous_mode = stat.S_IMODE(CONFIG_PATH.stat().st_mode) if previous_file is not None else None
        previous = {key: _read(key) for key in (QDISC, CONGESTION)}
        if 'bbr' not in _read(AVAILABLE).split():
            modprobe = shutil.which('modprobe')
            if modprobe:
                subprocess.run([modprobe, 'tcp_bbr'], capture_output=True, timeout=10)
            if 'bbr' not in _read(AVAILABLE).split():
                raise ValidationError('当前内核不支持 BBR，或无法加载 tcp_bbr 模块；未修改网络参数。'
                                      '请使用支持 BBR 的宿主机内核，容器内可能无法启用')
        try:
            _set(QDISC, 'fq')
            _set(CONGESTION, 'bbr')
            if _read(QDISC) != 'fq' or not enabled():
                raise ValidationError('内核未应用 fq / bbr 参数')
            atomic_write(CONFIG_PATH, CONFIG)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failures = []
            for key, value in previous.items():
                try:
                    _set(key, value)
                    if _read(key) != value:
                        raise ValidationError('运行参数未恢复')
                except (OSError, ValueError, subprocess.SubprocessError):
                    failures.append(key)
            try:
                if previous_file is None:
                    CONFIG_PATH.unlink(missing_ok=True)
                else:
                    atomic_write(CONFIG_PATH, previous_file)
                    os.chmod(CONFIG_PATH, previous_mode)
            except (OSError, ValueError):
                failures.append(str(CONFIG_PATH))
            if failures:
                raise ValidationError('开启 BBR 失败，部分恢复未完成，请手动检查：' + '、'.join(failures)) from error
            raise ValidationError('开启 BBR 失败，已恢复原有运行参数和配置；请检查内核支持、权限及磁盘空间') from error
