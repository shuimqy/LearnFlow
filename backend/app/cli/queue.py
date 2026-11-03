import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import zipfile

from redis.exceptions import RedisError
from rq import Worker

from app.core.config import ROOT, get_settings
from app.services.extraction_queue import QUEUE_NAME, redis_connection

REDIS_HOME = ROOT / ".local" / "redis"
VERSION = "8.10.3"
ARCHIVE = f"Redis-{VERSION}-Windows-x64-msys2.zip"
SHA256 = "af16df340525b431e9ec8dabfd625d5e7a233f82805b5418819904ea909c447f"
URL = f"https://github.com/redis-windows/redis-windows/releases/download/{VERSION}/{ARCHIVE}"


def available():
    try:
        return redis_connection().ping()
    except RedisError:
        return False


def executable():
    return next((REDIS_HOME / "runtime").rglob("redis-server.exe"), None)


def install():
    if available():
        print("Redis is already reachable.")
        return
    if os.name != "nt" or get_settings().redis_url not in {
        "redis://localhost:6379/0",
        "redis://127.0.0.1:6379/0",
    }:
        raise RuntimeError("Start your configured Redis server, or use docker compose up -d redis.")
    if executable():
        return
    REDIS_HOME.mkdir(parents=True, exist_ok=True)
    archive = REDIS_HOME / ARCHIVE
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        print(f"Downloading Redis {VERSION} Windows community build...")
        with urllib.request.urlopen(URL, timeout=60) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Redis archive checksum mismatch.")
    runtime = (REDIS_HOME / "runtime").resolve()
    runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            if not (runtime / entry.filename).resolve().is_relative_to(runtime):
                raise RuntimeError("Unexpected Redis archive path.")
        source.extractall(runtime)
    if not executable():
        raise RuntimeError("Redis executable was not found in the archive.")


def serve():
    if available():
        raise RuntimeError(
            "Redis is already running; this command will not take over that service."
        )
    install()
    binary = executable()
    data = REDIS_HOME / "data"
    data.mkdir(exist_ok=True)
    # 前台运行，由启动器持有进程树；只监听本机，不注册系统服务。
    subprocess.run(
        [
            str(binary),
            "--bind",
            "127.0.0.1",
            "--port",
            "6379",
            "--protected-mode",
            "yes",
            "--dir",
            str(data),
            "--appendonly",
            "yes",
            "--appendfsync",
            "everysec",
            "--save",
            "",
            "--maxmemory-policy",
            "noeviction",
        ],
        cwd=binary.parent,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["setup", "serve", "check", "status"])
    command = parser.parse_args().command
    if command == "setup":
        install()
    elif command == "serve":
        serve()
    elif command == "check":
        if not available():
            sys.exit(1)
        print("Redis is ready.")
    else:
        ready = available()
        workers = Worker.all(connection=redis_connection()) if ready else []
        print(
            json.dumps(
                {
                    "redis_available": ready,
                    "document_workers": sum(
                        QUEUE_NAME in worker.queue_names() for worker in workers
                    ),
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, RedisError, zipfile.BadZipFile):
        print(
            "Queue setup failed. Check Redis availability or the project-local runtime.",
            file=sys.stderr,
        )
        sys.exit(1)
