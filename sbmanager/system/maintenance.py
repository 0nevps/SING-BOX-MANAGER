"""Manager updates reuse the installer; uninstall touches only managed paths."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from sbmanager.security import ValidationError
from sbmanager.system.systemd import Systemd


INSTALL_DIR = Path('/opt/sbmanager')
DATA_DIR = Path('/var/lib/sbmanager')
CONFIG_DIR = Path('/etc/sbmanager')
COMMAND = Path('/usr/local/bin/sbmanager')
UNIT = Path('/etc/systemd/system') / Systemd.unit
DROP_INS = UNIT.with_name(Systemd.unit + '.d')
INSTALL_LOCK = Path('/run/sbmanager-install.lock')
DEFAULT_REPOSITORY = '0nevps/SING-BOX-MANAGER'


def update():
    """Fetch main's installer, then restart the menu against the selected build."""
    metadata = INSTALL_DIR / 'current' / '.source-repository'
    repository = metadata.read_text().strip() if metadata.exists() else DEFAULT_REPOSITORY
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValidationError('安装来源仓库格式无效，已停止更新，请检查 .source-repository')
    # Keep the downloaded script separate from our working directory and let the
    # installer perform its own confirmation, locking, backups, and rollback.
    with tempfile.TemporaryDirectory(prefix='sbmanager-update-') as directory:
        script = Path(directory) / 'install.sh'
        subprocess.run(
            ['curl', '--proto', '=https', '--tlsv1.2', '--retry', '3', '-fsSL',
             f'https://raw.githubusercontent.com/{repository}/main/install.sh', '-o', str(script)],
            check=True, timeout=120)
        subprocess.run(['bash', str(script), repository], check=True,
                       env={**os.environ, 'SBMANAGER_NO_MENU': '1'})
    # Never continue using already imported modules after switching current.
    os.execv(str(COMMAND), [str(COMMAND)])


def uninstall_paths():
    return (UNIT, DROP_INS, CONFIG_DIR, DATA_DIR, INSTALL_DIR, COMMAND)


@contextmanager
def exclusive_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValidationError('另一个安装、更新或数据操作正在进行，请等待完成后重试') from None
        yield
    finally:
        os.close(fd)


def _remove(path):
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


def uninstall():
    """Called only after the CLI has displayed paths and received confirmation."""
    paths = uninstall_paths()
    # Refuse redirected parent directories and mount points before stopping the
    # service. A symlink at a managed path is removed, never followed.
    for path in (*paths, INSTALL_LOCK):
        if path.parent.resolve() != path.parent or (not path.is_symlink() and path.is_mount()):
            raise ValidationError(f'卸载路径包含重定向的父目录或挂载点，已停止：{path}')
        if path.is_dir() and not path.is_symlink():
            for directory, children, _ in os.walk(path, followlinks=False):
                for name in children:
                    child = Path(directory) / name
                    if not child.is_symlink() and child.is_mount():
                        raise ValidationError(f'卸载目录内包含挂载点，已停止：{child}')
    with exclusive_lock(INSTALL_LOCK):
        if DATA_DIR.is_symlink():
            raise ValidationError('数据目录是符号链接，已停止卸载，请先检查实际数据位置')
        if DATA_DIR.exists():
            with exclusive_lock(DATA_DIR / 'state.lock'):
                _uninstall_files(paths)
        else:
            _uninstall_files(paths)
    # Keep the shared coordination lock inode until reboot. Removing a lock file
    # can let concurrent installers hold different inodes for the same pathname.


def _uninstall_files(paths):
    result = subprocess.run(
        ['systemctl', 'show', Systemd.unit, '--property=LoadState', '--value'],
        check=True, capture_output=True, text=True, timeout=15)
    if result.stdout.strip() != 'not-found':
        subprocess.run(['systemctl', 'disable', '--now', Systemd.unit], check=True, timeout=120)
    for path in (UNIT, DROP_INS):
        _remove(path)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
    # Leave the command and builds available if deleting configuration/data fails.
    for path in paths[2:]:
        _remove(path)
