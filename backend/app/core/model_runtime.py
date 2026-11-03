from contextlib import contextmanager
from contextvars import ContextVar

from app.core.config import get_settings

_settings = ContextVar("account_model_settings", default=None)


def model_settings():
    return _settings.get() or get_settings()


@contextmanager
def use_model_settings(settings):
    token = _settings.set(settings)
    try:
        yield
    finally:
        _settings.reset(token)
