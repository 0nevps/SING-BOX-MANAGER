"""Journaled deployment. A pending journal is recovered before the next mutation."""
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from sbmanager.core.config_builder import build
from sbmanager.security import ValidationError


def atomic_write(path, content):
    path = Path(path)
    if path.is_symlink():
        raise ValidationError('拒绝写入符号链接')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


class Deployment:
    def __init__(self, store, config_path, engine, service):
        self.store, self.config_path = store, Path(config_path)
        self.engine, self.service = engine, service
        self.journal = store.directory / 'transaction.json'
        self.backups = store.directory / 'backups'
        self.backups.mkdir(exist_ok=True, mode=0o700)
        self.backups.chmod(0o700)

    def snapshot(self):
        return {'state': self.store.path.read_text() if self.store.path.exists() else None,
                'config': self.config_path.read_text() if self.config_path.exists() else None,
                'active': self.service.active()}

    def backup(self):
        name = f'{time.time_ns()}-{uuid.uuid4().hex}.json'
        atomic_write(self.backups / name, encode(self.snapshot()))
        return name

    def recover(self):
        if not self.journal.exists():
            return
        previous = json.loads(self.journal.read_text())
        for path, key in ((self.store.path, 'state'), (self.config_path, 'config')):
            if previous[key] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, previous[key].encode())
        if previous['active']:
            self.service.restart()
            self.service.health(json.loads(previous['config']))
        else:
            self.service.stop()
        self.journal.unlink()

    def apply(self, state):
        from sbmanager.core.validation import validate_state
        validate_state(state)
        config = build(state, str(self.store.directory / 'acme'))
        candidate = self.store.directory / 'candidate.json'
        try:
            atomic_write(candidate, encode(config))
            self.engine.version()
            self.engine.check(candidate)
            if not self.service.active() and getattr(self.service, "preflight", None):
                self.service.preflight(config)
            previous = self.snapshot()
            self.backup()
            atomic_write(self.journal, encode(previous))
            try:
                atomic_write(self.config_path, encode(config))
                atomic_write(self.store.path, encode(state))
                self.service.restart()
                self.service.health(config)
                self.journal.unlink()
            except Exception as failure:
                try:
                    self.recover()
                except Exception as recovery:
                    raise ValidationError('应用和恢复均失败；恢复日志已保留，停止修改并检查服务') from recovery
                raise ValidationError('应用失败，已恢复原状态、配置及服务状态') from failure
            self.prune(state.get("backup_keep", 20))
        finally:
            candidate.unlink(missing_ok=True)

    def restore(self, name):
        if Path(name).name != name or not name.endswith('.json'):
            raise ValidationError('无效备份名称')
        snapshot = json.loads((self.backups / name).read_text())
        if snapshot['state'] is None:
            raise ValidationError('备份没有业务状态')
        state = json.loads(snapshot['state'])
        if state.get('schema_version') != 1:
            raise ValidationError('备份 schema 不受支持')
        self.apply(state)

    def prune(self, keep):
        if type(keep) is not int or keep < 1:
            raise ValidationError('至少保留一份备份')
        files = sorted(self.backups.glob('*.json'), reverse=True)
        for path in files[keep:]:
            path.unlink()
