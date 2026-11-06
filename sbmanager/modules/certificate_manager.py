"""Diagnostics only: issuance and renewal belong to sing-box."""
import socket
import ssl
from pathlib import Path


def inspect(state, acme_directory):
    domains = sorted({i['settings']['server_name'] for i in state['inbounds'].values()
                      if i['protocol'] != 'reality' and i.get('settings')})
    results = []
    for domain in domains:
        entry = {'domain': domain, 'issuer': 'sing-box ACME', 'public_http01': '需从公网验证 TCP 80 和域名路由'}
        try:
            entry['addresses'] = sorted({a[4][0] for a in socket.getaddrinfo(domain, 80)})
        except OSError:
            entry['dns_error'] = 'DNS 解析失败'
        results.append(entry)
    certificates = []
    for path in Path(acme_directory).rglob('*.crt'):
        try:
            data = ssl._ssl._test_decode_cert(str(path))
            certificates.append({'file': str(path.relative_to(acme_directory)), 'expires': data.get('notAfter'),
                                 'names': data.get('subjectAltName')})
        except (ValueError, ssl.SSLError):
            certificates.append({'file': path.name, 'error': '证书读取失败'})
    return {'domains': results, 'certificates': certificates,
            'note': '本地 DNS 和缓存证书不代表公网挑战已通过；请同时检查服务日志'}
