"""Validation and credential generation shared by business modules."""
import secrets
import uuid


class ValidationError(ValueError):
    pass


class PortInUse(ValidationError):
    """A listener conflicts with a reserved or currently occupied port."""


def text(value, label):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValidationError(f'{label}不能为空，也不能包含换行、制表符等控制字符。请重新输入')
    return value.strip()


def identifier():
    return str(uuid.uuid4())


def credential(protocol):
    return secrets.token_urlsafe(24) if protocol in ('hysteria2', 'anytls') else identifier()
