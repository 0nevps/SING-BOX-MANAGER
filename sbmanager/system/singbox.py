"""Bounded subprocess interface. Configuration failures never echo secrets."""
import re
import subprocess
from sbmanager.security import ValidationError


class SingBox:
    def __init__(self, binary='sing-box'):
        self.binary = str(binary)

    def version(self):
        result = subprocess.run([self.binary, 'version'], capture_output=True, text=True, timeout=10, check=True)
        if not re.search(r'sing-box version 1\.14\.\d+', result.stdout):
            raise ValidationError('当前仅支持经过验证的 sing-box 1.14.x')
        if 'with_acme' not in result.stdout:
            raise ValidationError('sing-box 缺少 with_acme 支持')
        return result.stdout.splitlines()[0]

    def check(self, path):
        result = subprocess.run([self.binary, 'check', '-c', str(path)], capture_output=True, timeout=30)
        if result.returncode:
            raise ValidationError('sing-box 配置校验失败；未应用配置（错误输出可能含敏感数据，已隐藏）')

    def keypair(self):
        result = subprocess.run([self.binary, 'generate', 'reality-keypair'], capture_output=True, text=True, timeout=10, check=True)
        pairs = dict(line.split(': ', 1) for line in result.stdout.strip().splitlines())
        return pairs['PrivateKey'], pairs['PublicKey']
