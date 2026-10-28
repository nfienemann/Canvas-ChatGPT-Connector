"""Authenticated field encryption; keys belong to an engine, never a global tenant."""

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

PREFIX = "bridge-sealed-v1:"
SECRET_FIELDS = frozenset({"access_token", "refresh_token", "client_secret", "code_verifier"})


def reject_secrets(value):
    if isinstance(value, dict):
        if SECRET_FIELDS & {str(k).lower() for k in value}:
            raise ValueError("Authentication secrets cannot be stored in academic caches.")
        for item in value.values():
            reject_secrets(item)
    elif isinstance(value, list):
        for item in value:
            reject_secrets(item)


class Protected(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, purpose, *, academic=False):
        super().__init__()
        self.purpose, self.academic = purpose, academic

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if self.academic:
            reject_secrets(value)
        vault = getattr(dialect, "bridge_vault", None)
        if vault is None:
            raise ValueError("Encrypted storage has not been initialized.")
        return PREFIX + vault.seal({"value": value}, "database-field", self.purpose)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        vault = getattr(dialect, "bridge_vault", None)
        if vault is None or not isinstance(value, str) or not value.startswith(PREFIX):
            raise ValueError("Encrypted storage migration or key is required.")
        return vault.open(value[len(PREFIX) :], "database-field", self.purpose)["value"]
