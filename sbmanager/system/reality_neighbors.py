"""Read-only IPv4 neighbor discovery for the REALITY node form."""
import concurrent.futures
import functools
import ipaddress
import json
import re
import socket
import ssl
import statistics
import subprocess
import time
import urllib.request


DOMAIN = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')
PAIR_LIMIT = 24
FINALISTS = 5


class LookupFailure(ValueError):
    pass


def addresses(host):
    try:
        records = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return []
    ips = {ipaddress.IPv4Address(record[4][0]) for record in records}
    return sorted(ip for ip in ips if ip.is_global and not ip.is_multicast)


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise LookupFailure('响应超过大小限制')
        return json.loads(data)
    except (OSError, ValueError) as error:
        raise LookupFailure(str(error)) from error


def routing(ip):
    try:
        data = fetch(f'https://stat.ripe.net/data/network-info/data.json?resource={ip}')['data']
        prefix = ipaddress.IPv4Network(data['prefix'])
        asns = data['asns']
        if ip not in prefix or not isinstance(asns, list):
            raise ValueError
        return prefix, frozenset(int(asn) for asn in asns)
    except (ValueError, KeyError, TypeError):
        return None, frozenset()


def certificate_domains(network):
    try:
        entries = fetch(f'https://bgp.he.net/certs/api/ip-search?ip={network}')['entries']
        if not isinstance(entries, list):
            raise TypeError
        names = set()
        for entry in entries:
            hostnames = entry['hostnames']
            if not isinstance(hostnames, list):
                raise TypeError
            for name in hostnames:
                if isinstance(name, str) and DOMAIN.fullmatch(name.lower()):
                    names.add(name.lower())
        return names
    except (KeyError, TypeError) as error:
        raise LookupFailure('证书数据格式不符') from error


def handshake(domain, ip, port):
    context = ssl.create_default_context()
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.set_alpn_protocols(['h2'])
    try:
        start = time.monotonic()
        with socket.create_connection((str(ip), port), timeout=3) as connection:
            with context.wrap_socket(connection, server_hostname=domain) as tls:
                if tls.selected_alpn_protocol() == 'h2':
                    return (time.monotonic() - start) * 1000
    except OSError:
        pass
    return None


def http_status(domain, ip, port):
    try:
        result = subprocess.run([
            'curl', '-q', '--silent', '--head', '--http2', '--tlsv1.3', '--tls-max', '1.3',
            '--noproxy', '*', '--resolve', f'{domain}:{port}:{ip}', '--max-time', '4',
            '--output', '/dev/null', '--write-out', '%{http_version} %{http_code}',
            f'https://{domain}:{port}/',
        ], capture_output=True, text=True, timeout=5)
        if not result.returncode and re.fullmatch(r'[\d.]+ [1-5]\d\d', result.stdout):
            return 'HTTP/' + result.stdout
    except (OSError, subprocess.TimeoutExpired):
        pass
    return 'HTTP 未取得'


def recommend(entry, node_ips, port):
    lookup = functools.lru_cache(maxsize=None)(routing)
    prefix, asns = lookup(entry)
    local = ipaddress.IPv4Network(f'{entry}/24', strict=False)
    networks = [prefix] if prefix and prefix.subnet_of(local) else [local]
    if prefix and 18 <= prefix.prefixlen < 24:
        networks.append(prefix)
    notes = [] if prefix else ['入口 BGP 数据不可用，按 /24 查找；前缀和 ASN 关系未知。']
    names = set()
    for network in networks:
        try:
            names.update(certificate_domains(network))
        except LookupFailure as error:
            notes.append(f'{network} 证书数据源查询失败：{error}')
    ordered = sorted(names, key=lambda name: (len(name), name))
    if len(ordered) > PAIR_LIMIT:
        notes.append('域名解析预算已用尽；仍有未测试域名。')
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        selected = ordered[:PAIR_LIMIT]
        resolved = pool.map(addresses, selected)
        pairs = [(name, ip) for name, ips in zip(selected, resolved) for ip in ips
                 if ip not in node_ips and any(ip in net for net in networks)]
        if len(pairs) > PAIR_LIMIT:
            notes.append('握手测试预算已用尽；仍有未测试地址。')
        pairs = pairs[:PAIR_LIMIT]

        def sample(pair):
            return handshake(*pair, port)

        first = sorted((delay, pair) for pair, delay in zip(pairs, pool.map(sample, pairs))
                       if delay is not None)

        def retest(item):
            delay, (domain, ip) = item
            times = [delay] + [sample((domain, ip)) for _ in range(2)]
            valid = [value for value in times if value is not None]
            return domain, ip, len(valid), statistics.median(valid), http_status(domain, ip, port)

        results = sorted(pool.map(retest, first[:FINALISTS]), key=lambda row: (-row[2], row[3], row[0], row[1]))
    rows = []
    for domain, ip, successes, median, status in results:
        other_prefix, other_asns = lookup(ip)
        relation = '同 /24' if ip in local else '不同 /24'
        relation += ' · ' + ('前缀未知' if not (prefix and other_prefix) else
                             '同宣告前缀' if prefix == other_prefix else '不同宣告前缀')
        relation += ' · ' + ('ASN 未知' if not (asns and other_asns) else
                             '同 ASN' if asns & other_asns else '不同 ASN')
        rows.append((domain, f'{domain} · {ip} · {relation} · {successes}/3 次成功 · 中位 {median:.1f} ms · {status}'))
    if not rows:
        notes.append('本次已查询和测试的范围内无合格候选。' if pairs or names or not notes else '没有可供验证的候选数据。')
    return rows, notes
