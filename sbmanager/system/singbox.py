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
            raise ValidationError('sing-box 版本不兼容，目前仅支持 1.14.x。请检查使用的 sing-box 程序版本')
        if 'with_acme' not in result.stdout:
            raise ValidationError('这个 sing-box 程序不支持自动申请证书（缺少 with_acme）。请使用带有此功能的版本')
        return result.stdout.splitlines()[0]

    def check(self, path):
        result = subprocess.run([self.binary, 'check', '-c', str(path)], capture_output=True, timeout=30)
        if result.returncode:
            raise ValidationError('sing-box 配置检查未通过，新配置没有生效。请核对节点和出口设置；详细错误可能含密码或密钥，已隐藏')

    def keypair(self):
        result = subprocess.run([self.binary, 'generate', 'reality-keypair'], capture_output=True, text=True, timeout=10, check=True)
        pairs = dict(line.split(': ', 1) for line in result.stdout.strip().splitlines())
        return pairs['PrivateKey'], pairs['PublicKey']
