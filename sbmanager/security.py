"""Validation and credential generation shared by business modules."""
import secrets
import uuid


class ValidationError(ValueError):
    pass


def text(value, label):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValidationError(f'{label}不能为空或包含控制字符')
    return value.strip()


def identifier():
    return str(uuid.uuid4())


def credential(protocol):
    return secrets.token_urlsafe(24) if protocol == 'hysteria2' else identifier()
