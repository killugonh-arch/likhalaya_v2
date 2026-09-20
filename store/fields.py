"""Encrypted text field for storing messages at rest."""
from django.conf import settings
from django.db import models
from cryptography.fernet import Fernet, InvalidToken


def _fernet():
    key = settings.MESSAGE_ENCRYPTION_KEY
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


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
            # unencrypted old row, return as-is
            return value