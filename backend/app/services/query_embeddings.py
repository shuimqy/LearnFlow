import hashlib
import threading
import time
from collections import OrderedDict

from app.services.account_models import default_config, fingerprint

TTL_SECONDS = 300
MAX_ENTRIES = 256
_entries = OrderedDict()
_lock = threading.Lock()
_generation = 0


def query_embedding(settings, user_id, course_id, question, embed):
    identity = fingerprint(default_config("embedding", settings))
    credential = hashlib.sha256(settings.embedding_api_key.get_secret_value().encode()).hexdigest()
    digest = hashlib.sha256(question.encode()).hexdigest()
    key = (user_id, course_id, identity, credential, digest)
    now = time.monotonic()
    with _lock:
        generation = _generation
        expired = [item for item, (deadline, _) in _entries.items() if deadline <= now]
        for item in expired:
            _entries.pop(item, None)
        cached = _entries.get(key)
        if cached:
            _entries.move_to_end(key)
            return list(cached[1])
    vector = embed(question)
    with _lock:
        if generation != _generation:
            return vector
        _entries[key] = (time.monotonic() + TTL_SECONDS, tuple(vector))
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)
    return vector


def clear_query_cache(user_id=None, course_id=None):
    global _generation
    with _lock:
        _generation += 1
        keys = [
            key
            for key in _entries
            if (user_id is None or key[0] == user_id) and (course_id is None or key[1] == course_id)
        ]
        for key in keys:
            _entries.pop(key, None)
