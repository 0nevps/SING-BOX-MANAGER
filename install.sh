#!/usr/bin/env bash
set -euo pipefail
umask 077
# Usage: bash install.sh OWNER/REPOSITORY [vMAJOR.MINOR.PATCH]
repo=${1:-}
version=${2:-}
[[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo '用法: bash install.sh OWNER/REPOSITORY [v版本]' >&2; exit 1; }
[[ $(uname -s) == Linux && $EUID -eq 0 ]] || { echo '需要 Linux root 环境' >&2; exit 1; }
# shellcheck disable=SC1091
source /etc/os-release
case "$ID:$VERSION_ID" in debian:12|debian:13|ubuntu:22.04|ubuntu:24.04) ;; *) echo '尚未验证此系统版本' >&2; exit 1;; esac
command -v systemctl >/dev/null || { echo '需要 systemd' >&2; exit 1; }
case $(uname -m) in x86_64) arch=amd64;; aarch64|arm64) arch=arm64;; *) echo '不支持的 CPU 架构' >&2; exit 1;; esac
apt-get update
apt-get install -y python3 ca-certificates curl tar iproute2 util-linux
exec 9>/run/sbmanager-install.lock
flock -n 9 || { echo '已有安装操作进行中' >&2; exit 1; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fetch() { curl --proto '=https' --tlsv1.2 --retry 3 -fsSL "$1" -o "$2"; }
if [[ -z "$version" ]]; then
    fetch "https://api.github.com/repos/$repo/releases/latest" "$tmp/release.json"
    version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag_name"])' "$tmp/release.json")
fi
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo '无效发布版本' >&2; exit 1; }
base="https://github.com/$repo/releases/download/$version"
fetch "$base/sbmanager-$version.tar.gz" "$tmp/package.tar.gz"
fetch "$base/SHA256SUMS" "$tmp/SHA256SUMS"
python3 - "$tmp" "$version" <<'PY'
import hashlib,pathlib,sys,tarfile
root=pathlib.Path(sys.argv[1]); name=f'sbmanager-{sys.argv[2]}.tar.gz'
expected={line.split()[1]:line.split()[0] for line in (root/'SHA256SUMS').read_text().splitlines()}
if hashlib.sha256((root/'package.tar.gz').read_bytes()).hexdigest()!=expected[name]:
    raise SystemExit('发布包校验失败')
with tarfile.open(root/'package.tar.gz') as archive:
    for member in archive.getmembers():
        path=pathlib.PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
            raise SystemExit('不安全的发布包路径')
    archive.extractall(root/'package')
PY
# Pin the engine to the version validated by this release.
engine_version=1.14.4
engine_name="sing-box-$engine_version-linux-$arch"
fetch "https://github.com/SagerNet/sing-box/releases/download/v$engine_version/$engine_name.tar.gz" "$tmp/engine.tar.gz"
fetch "https://api.github.com/repos/SagerNet/sing-box/releases/tags/v$engine_version" "$tmp/engine-release.json"
python3 - "$tmp" "$engine_name" <<'PY'
import hashlib,json,pathlib,sys,tarfile
root=pathlib.Path(sys.argv[1]); name=sys.argv[2]
assets=json.loads((root/"engine-release.json").read_text())["assets"]
asset=next(a for a in assets if a["name"]==name+".tar.gz")
expected=asset.get("digest", "")
if not expected.startswith("sha256:") or "sha256:"+hashlib.sha256((root/"engine.tar.gz").read_bytes()).hexdigest()!=expected:
    raise SystemExit('sing-box 校验失败')
with tarfile.open(root/'engine.tar.gz') as archive:
    member=archive.getmember(name+'/sing-box')
    if not member.isfile(): raise SystemExit('无效内核文件')
    (root/'sing-box').write_bytes(archive.extractfile(member).read())
PY
chmod 700 "$tmp/sing-box"
"$tmp/sing-box" version | grep -q with_acme
mkdir -p /opt/sbmanager/releases /var/lib/sbmanager /etc/sbmanager
chmod 700 /var/lib/sbmanager /etc/sbmanager
if [[ -e /opt/sbmanager/releases/$version ]]; then
    echo '此版本已存在；保留现有部署。'
    exit 0
fi
old=$(readlink /opt/sbmanager/current || true)
if [[ -f /var/lib/sbmanager/transaction.json ]]; then
    echo '存在未恢复的部署事务，请先运行旧版 sbmanager 完成恢复' >&2
    exit 1
fi
python3 - /var/lib/sbmanager/state.json <<'CHECK_STATE'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1])
if p.exists() and json.loads(p.read_text()).get('schema_version') != 1:
    raise SystemExit('现有状态 schema 不受支持，停止升级')
CHECK_STATE
if [[ -n "$old" ]]; then
    [[ -r /dev/tty ]] || { echo '升级需要交互终端' >&2; exit 1; }
    read -r -p "升级至 $version？输入 yes: " answer </dev/tty
    [[ "$answer" == yes ]] || exit 0
fi
# Do not run package installation concurrently with manager mutations.
exec 8>/var/lib/sbmanager/state.lock
flock -x 8
if [[ -f /etc/sbmanager/config.json ]]; then
    "$tmp/sing-box" check -c /etc/sbmanager/config.json
fi
backup_dir="/var/lib/sbmanager/install-backups/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$backup_dir"
for source_file in /var/lib/sbmanager/state.json /etc/sbmanager/config.json /etc/systemd/system/sbmanager-sing-box.service /usr/local/bin/sbmanager; do
    if [[ -f "$source_file" ]]; then cp -p "$source_file" "$backup_dir/$(basename "$source_file")"; fi
done
was_active=0
if systemctl is-active --quiet sbmanager-sing-box.service; then was_active=1; fi
rollback_ready=1
rollback_install() {
    result=$?
    if [[ $result -ne 0 && $rollback_ready -eq 1 ]]; then
        if [[ -n "$old" ]]; then
            ln -sfn "$old" /opt/sbmanager/current.rollback
            mv -Tf /opt/sbmanager/current.rollback /opt/sbmanager/current
        else
            rm -f /opt/sbmanager/current
        fi
        if [[ -f "$backup_dir/sbmanager-sing-box.service" ]]; then
            cp -p "$backup_dir/sbmanager-sing-box.service" /etc/systemd/system/sbmanager-sing-box.service
        else
            systemctl disable --now sbmanager-sing-box.service || true
            rm -f /etc/systemd/system/sbmanager-sing-box.service
        fi
        if [[ -f "$backup_dir/sbmanager" ]]; then
            cp -p "$backup_dir/sbmanager" /usr/local/bin/sbmanager
        else
            rm -f /usr/local/bin/sbmanager
        fi
        systemctl daemon-reload || true
        if [[ $was_active -eq 1 ]]; then systemctl restart sbmanager-sing-box.service || true; fi
        echo "安装失败；已尝试恢复旧程序，备份位于 $backup_dir" >&2
    fi
    rm -rf "$tmp"
}
trap rollback_install EXIT
cp -R "$tmp/package" "/opt/sbmanager/releases/$version"
install -m 755 "$tmp/sing-box" "/opt/sbmanager/releases/$version/sing-box"
ln -s "/opt/sbmanager/releases/$version" /opt/sbmanager/current.new
mv -Tf /opt/sbmanager/current.new /opt/sbmanager/current
cat > /usr/local/bin/sbmanager <<'WRAPPER'
#!/bin/sh
exec python3 /opt/sbmanager/current/main.py --system --sing-box /opt/sbmanager/current/sing-box "$@"
WRAPPER
chmod 755 /usr/local/bin/sbmanager
cat > /etc/systemd/system/sbmanager-sing-box.service <<'UNIT'
[Unit]
Description=Sing-Box Manager engine
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=/opt/sbmanager/current/sing-box run -c /etc/sbmanager/config.json
Restart=on-failure
RestartSec=5
UMask=0077
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable sbmanager-sing-box.service
if [[ $was_active -eq 1 ]]; then
    if ! systemctl restart sbmanager-sing-box.service || ! systemctl is-active --quiet sbmanager-sing-box.service; then
        if [[ -n "$old" ]]; then
            ln -s "$old" /opt/sbmanager/current.rollback
            mv -Tf /opt/sbmanager/current.rollback /opt/sbmanager/current
            systemctl restart sbmanager-sing-box.service
        fi
        echo '升级失败，已尝试恢复旧程序，请检查服务状态' >&2
        exit 1
    fi
fi
rollback_ready=0
echo '安装完成。运行 sbmanager 开始配置；服务和证书尚需完成初始化。'
