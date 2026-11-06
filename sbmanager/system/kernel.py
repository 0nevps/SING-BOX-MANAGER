"""Upgrade to an explicitly selected 1.14.x official build, preserving rollback."""
import hashlib
import io
import json
import platform
import re
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from sbmanager.core.transaction_manager import atomic_write
from sbmanager.security import ValidationError
from sbmanager.system.singbox import SingBox


def download(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read(128 * 1024 * 1024)


def upgrade(deployment, version):
    if not re.fullmatch(r'1\.14\.\d+', version):
        raise ValidationError('请填写完整的 sing-box 1.14.x 稳定版本号，例如 1.14.4，不要加 v')
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if platform.system() != 'Linux' or arch is None:
        raise ValidationError('此升级功能只支持 Linux x86_64 或 aarch64 系统，请检查 VPS 的系统和 CPU 类型')
    release = json.loads(download(f'https://api.github.com/repos/SagerNet/sing-box/releases/tags/v{version}'))
    if release.get('prerelease') or release.get('draft'):
        raise ValidationError('这个 sing-box 版本是预发布版或草稿版，不能用于此升级。请选择稳定版本')
    name = f'sing-box-{version}-linux-{arch}'
    asset = next((a for a in release['assets'] if a['name'] == name + '.tar.gz'), None)
    if not asset or not asset.get('digest', '').startswith('sha256:'):
        raise ValidationError('找不到对应的 sing-box 下载包或 SHA-256 校验信息。无法确认文件完整性，已停止升级')
    # Construct the official URL rather than following an arbitrary metadata URL.
    data = download(f'https://github.com/SagerNet/sing-box/releases/download/v{version}/{name}.tar.gz')
    if 'sha256:' + hashlib.sha256(data).hexdigest() != asset['digest']:
        raise ValidationError('下载的 sing-box 文件与官方 SHA-256 校验信息不一致，已停止升级。请检查下载来源和网络后重试')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        member = archive.getmember(name + '/sing-box')
        if not member.isfile():
            raise ValidationError('下载包中的 sing-box 程序文件格式不正确，已停止升级')
        binary_data = archive.extractfile(member).read()
    binary = Path(deployment.engine.binary).resolve()
    candidate = binary.with_name('sing-box.candidate')
    backup = binary.with_name('sing-box.previous')
    try:
        atomic_write(candidate, binary_data)
        candidate.chmod(0o755)
        engine = SingBox(candidate)
        engine.version()
        if deployment.config_path.exists():
            engine.check(deployment.config_path)
        with deployment.store.locked():
            if deployment.config_path.exists():
                engine.check(deployment.config_path)
            was_active = deployment.service.active()
            atomic_write(backup, binary.read_bytes())
            backup.chmod(0o755)
            atomic_write(binary, binary_data)
            binary.chmod(0o755)
            try:
                if was_active:
                    deployment.service.restart()
                    deployment.service.health(json.loads(deployment.config_path.read_text()))
            except Exception:
                atomic_write(binary, backup.read_bytes())
                binary.chmod(0o755)
                deployment.service.restart()
                raise ValidationError('新版 sing-box 启动检查未通过，已换回旧版并重启服务。请到“服务管理 > 查看状态”和“查看日志”确认') from None
    finally:
        candidate.unlink(missing_ok=True)
