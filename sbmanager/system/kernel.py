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
        raise ValidationError('仅允许明确指定 1.14.x 稳定版本')
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if platform.system() != 'Linux' or arch is None:
        raise ValidationError('内核升级需要受支持的 Linux 架构')
    release = json.loads(download(f'https://api.github.com/repos/SagerNet/sing-box/releases/tags/v{version}'))
    if release.get('prerelease') or release.get('draft'):
        raise ValidationError('拒绝安装预发布内核')
    name = f'sing-box-{version}-linux-{arch}'
    asset = next((a for a in release['assets'] if a['name'] == name + '.tar.gz'), None)
    if not asset or not asset.get('digest', '').startswith('sha256:'):
        raise ValidationError('发布产物缺少 SHA-256 摘要')
    # Construct the official URL rather than following an arbitrary metadata URL.
    data = download(f'https://github.com/SagerNet/sing-box/releases/download/v{version}/{name}.tar.gz')
    if 'sha256:' + hashlib.sha256(data).hexdigest() != asset['digest']:
        raise ValidationError('内核校验失败')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        member = archive.getmember(name + '/sing-box')
        if not member.isfile():
            raise ValidationError('无效内核文件')
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
                raise ValidationError('新内核启动失败，已恢复旧内核') from None
    finally:
        candidate.unlink(missing_ok=True)
