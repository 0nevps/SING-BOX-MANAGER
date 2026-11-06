"""Locked read-modify-write operations; failed mutations never reach disk."""
import copy
import fcntl
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager

from sbmanager.security import ValidationError
from sbmanager.core.validation import validate_state


def empty_state():
    return {'schema_version': 1, 'users': {}, 'inbounds': {}, 'egress': {}, 'bindings': {}}


class StateStore:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser()
        if self.directory.is_symlink():
            raise ValidationError('状态目录不能是符号链接')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.path = self.directory / 'state.json'
        self.deployment = None

    @contextmanager
    def locked(self):
        fd = os.open(self.directory / 'state.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.deployment:
                self.deployment.recover()
            yield

    def _read(self):
        if self.path.is_symlink():
            raise ValidationError('状态文件不能是符号链接')
        if not self.path.exists():
            return empty_state()
        self.path.chmod(0o600)
        with self.path.open(encoding='utf-8') as stream:
            state = json.load(stream)
        if not isinstance(state, dict) or state.get('schema_version') != 1:
            raise ValidationError('不支持的状态 schema 版本')
        for key in ('users', 'inbounds', 'egress', 'bindings'):
            if not isinstance(state.get(key), dict):
                raise ValidationError(f'状态字段损坏: {key}')
        validate_state(state)
        return state

    def read(self):
        with self.locked():
            return self._read()

    def update(self, mutation):
        with self.locked():
            state = self._read()
            result = mutation(state)
            validate_state(state)
            if self.deployment and state.get("deployed"):
                self.deployment.apply(state)
                return copy.deepcopy(result)
            fd, temporary = tempfile.mkstemp(prefix='.state-', dir=self.directory)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(state, stream, ensure_ascii=False, indent=2)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return copy.deepcopy(result)
