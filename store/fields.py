"""Encrypted text field for storing messages at rest."""
from django.conf import settings
from django.db import models
from cryptography.fernet import Fernet, InvalidToken, MultiFernet


def _fernet():
    """Current key encrypts; current + any MESSAGE_ENCRYPTION_KEY_OLD keys decrypt."""
    keys = [settings.MESSAGE_ENCRYPTION_KEY] + list(getattr(settings, 'MESSAGE_ENCRYPTION_KEY_OLD', []))
    fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in keys if k]
    return MultiFernet(fernets)


class EncryptedTextField(models.TextField):
    """TextField that encrypts on save and decrypts on read."""

    def get_prep_value(self, value):
        if value is None or value == '':
            return value
        value = str(value)
        return _fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except (InvalidToken, ValueError):
            # unencrypted old row, or encrypted with a key we don't have: return as-is
            return value