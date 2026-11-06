"""Diagnostics only: issuance and renewal belong to sing-box."""
import socket
import ssl
from pathlib import Path


def inspect(state, acme_directory):
    domains = sorted({i['settings']['server_name'] for i in state['inbounds'].values()
                      if i['protocol'] != 'reality' and i.get('settings')})
    results = []
    for domain in domains:
        entry = {'domain': domain, 'issuer': 'sing-box ACME', 'public_http01': '申请证书需要外网通过域名访问 VPS 的 TCP 80 端口，请检查 DNS、防火墙、安全组和转发规则'}
        try:
            entry['addresses'] = sorted({a[4][0] for a in socket.getaddrinfo(domain, 80)})
        except OSError:
            entry['dns_error'] = '找不到域名对应的 IP，请检查域名拼写和 DNS 记录是否已生效'
        results.append(entry)
    certificates = []
    for path in Path(acme_directory).rglob('*.crt'):
        try:
            data = ssl._ssl._test_decode_cert(str(path))
            certificates.append({'file': str(path.relative_to(acme_directory)), 'expires': data.get('notAfter'),
                                 'names': data.get('subjectAltName')})
        except (ValueError, ssl.SSLError):
            certificates.append({'file': path.name, 'error': '无法读取证书文件，请检查文件是否完整、格式是否正确'})
    return {'domains': results, 'certificates': certificates,
            'note': '这里仅显示域名解析结果和本地保存的证书，不代表证书申请或续期已成功。domains 是域名检查，certificates 是本地证书，expires 是到期时间；证书由 sing-box 自动申请和续期，失败时请选菜单 19 查看日志'}
