import argparse
import hashlib
import json
import os
import secrets
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.core.config import ROOT, get_settings

POSTGRES_HOME = ROOT / ".local" / "postgres"
RUNTIME = POSTGRES_HOME / "runtime"
BIN = RUNTIME / "Library" / "bin"
DATA = POSTGRES_HOME / "data"
LOG = ROOT / ".local" / "logs" / "postgres.log"
MICROMAMBA_VERSION = "2.10.0"
MICROMAMBA_SHA256 = "6283f25f8142606d86e81a43c7103b5d4f1d5c2027e3f9d7326eff23b33930d8"
MICROMAMBA_URL = (
    f"https://conda.anaconda.org/conda-forge/win-64/micromamba-{MICROMAMBA_VERSION}-0.tar.bz2"
)


def run(arguments, *, capture=False, env=None, check=True):
    return subprocess.run(
        [str(value) for value in arguments],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        check=check,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def native_env():
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(BIN), str(RUNTIME / "Library" / "lib"), env.get("PATH", "")])
    env["PGCLIENTENCODING"] = "UTF8"
    return env


def create_env():
    path = ROOT / ".env"
    if path.exists():
        return
    password = secrets.token_urlsafe(32)
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    text = text.replace("learnflow_local", password)
    text = text.replace("MANAGE_LOCAL_POSTGRES=false", "MANAGE_LOCAL_POSTGRES=true")
    path.write_text(text, encoding="utf-8")
    print("Created .env for a project-local PostgreSQL instance.")
    get_settings.cache_clear()


def install_runtime():
    if sys.platform != "win32":
        raise RuntimeError("Use Docker Compose or an existing PostgreSQL server on this platform.")
    if (BIN / "postgres.exe").is_file() and (RUNTIME / "Library" / "lib" / "vector.dll").is_file():
        return
    POSTGRES_HOME.mkdir(parents=True, exist_ok=True)
    manager = POSTGRES_HOME / "micromamba.exe"
    if not manager.exists():
        archive_path = POSTGRES_HOME / f"micromamba-{MICROMAMBA_VERSION}.tar.bz2"
        if (
            not archive_path.exists()
            or hashlib.sha256(archive_path.read_bytes()).hexdigest() != MICROMAMBA_SHA256
        ):
            print("Downloading the native package installer...")
            with urllib.request.urlopen(
                MICROMAMBA_URL, timeout=60, context=ssl.create_default_context()
            ) as response:
                archive_path.write_bytes(response.read())
        if hashlib.sha256(archive_path.read_bytes()).hexdigest() != MICROMAMBA_SHA256:
            raise RuntimeError("Package installer checksum mismatch.")
        with tarfile.open(archive_path) as archive:
            member = next(
                item for item in archive.getmembers() if item.name.endswith("/micromamba.exe")
            )
            with archive.extractfile(member) as binary:
                manager.write_bytes(binary.read())
    print("Installing PostgreSQL 16 and pgvector 0.8.6 (native binaries, no Python environment)...")
    action = "install" if (RUNTIME / "conda-meta").exists() else "create"
    run(
        [
            manager,
            "--no-rc",
            "--root-prefix",
            POSTGRES_HOME / "packages",
            action,
            "--yes",
            "--prefix",
            RUNTIME,
            "--channel",
            "conda-forge",
            "--strict-channel-priority",
            "postgresql=16",
            "pgvector=0.8.6",
        ]
    )
    if (
        not (BIN / "postgres.exe").exists()
        or not (RUNTIME / "Library" / "lib" / "vector.dll").exists()
    ):
        raise RuntimeError("PostgreSQL or pgvector binaries are missing after installation.")
    manifest = run([manager, "--no-rc", "list", "--prefix", RUNTIME, "--explicit"], capture=True)
    (POSTGRES_HOME / "runtime-packages.txt").write_text(manifest.stdout, encoding="utf-8")


def connect(url, database=None):
    if database:
        url = url.set(database=database)
    return psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        connect_timeout=5,
        autocommit=True,
    )


def initialize(url):
    if (DATA / "PG_VERSION").exists():
        if (DATA / "PG_VERSION").read_text().strip() != "16":
            raise RuntimeError("The local data directory belongs to another PostgreSQL version.")
        return
    if DATA.exists() and any(DATA.iterdir()):
        raise RuntimeError(
            "The local PostgreSQL data directory is not empty; initialization stopped."
        )
    if not url.username or not url.password:
        raise RuntimeError("Set a database username and password in DATABASE_URL.")
    POSTGRES_HOME.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(dir=POSTGRES_HOME, prefix="init-password-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as password_file:
            password_file.write(url.password)
        run(
            [
                BIN / "initdb.exe",
                "--pgdata",
                DATA,
                "--username",
                url.username,
                "--encoding",
                "UTF8",
                "--locale",
                "C",
                "--auth-host",
                "scram-sha-256",
                "--auth-local",
                "scram-sha-256",
                "--pwfile",
                filename,
            ],
            env=native_env(),
        )
    finally:
        Path(filename).unlink(missing_ok=True)
    with (DATA / "postgresql.conf").open("a", encoding="utf-8") as config:
        config.write(
            f"\nlisten_addresses = '127.0.0.1'\nport = {url.port or 5432}\ntimezone = 'UTC'\n"
        )


def ensure_database(url):
    with connect(url, "postgres") as admin:
        exists = admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)
        ).fetchone()
        if not exists:
            admin.execute(
                sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(sql.Identifier(url.database))
            )
    with connect(url) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")


def ensure():
    settings = get_settings()
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        print("Explicit SQLite configuration is active (test mode).")
        return
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("DATABASE_URL must use PostgreSQL.")
    if settings.manage_local_postgres:
        if url.host not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("Managed PostgreSQL must use a loopback address.")
        install_runtime()
        initialize(url)
        running = run(
            [BIN / "pg_ctl.exe", "--pgdata", DATA, "status"],
            capture=True,
            env=native_env(),
            check=False,
        )
        if running.returncode != 0:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            print("Starting project-local PostgreSQL...")
            run(
                [
                    BIN / "pg_ctl.exe",
                    "--pgdata",
                    DATA,
                    "--log",
                    LOG,
                    "--wait",
                    "--timeout",
                    "30",
                    "start",
                ],
                env=native_env(),
            )
        ensure_database(url)
    else:
        with connect(url) as connection:
            connection.execute("SELECT 1")
    print(f"Database ready: PostgreSQL at {url.host}:{url.port or 5432}/{url.database}")


def test_environment(browser=False):
    settings = get_settings()
    url = make_url(settings.test_database_url or settings.database_url)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("PostgreSQL is required for integration tests.")
    name = "learnflow_browser_test" if browser else url.database
    if not name or not name.endswith("_test"):
        raise RuntimeError("The integration test database name must end in _test.")
    target = url.set(database=name)
    ensure_database(target)
    return {"DATABASE_URL": target.render_as_string(hide_password=False)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["setup", "ensure", "info", "stop", "test-env", "browser-env"]
    )
    args = parser.parse_args()
    if args.command == "setup":
        create_env()
        ensure()
        if get_settings().test_database_url:
            test_environment()
    elif args.command == "ensure":
        ensure()
    elif args.command in {"test-env", "browser-env"}:
        print(json.dumps(test_environment(browser=args.command == "browser-env")))
    elif args.command == "stop":
        if not get_settings().manage_local_postgres:
            raise RuntimeError("The configured database is not managed by this project.")
        if (DATA / "PG_VERSION").exists():
            run(
                [BIN / "pg_ctl.exe", "--pgdata", DATA, "--wait", "--mode", "fast", "stop"],
                env=native_env(),
            )
    else:
        url = make_url(get_settings().database_url)
        with connect(url) as connection:
            version = connection.execute("SELECT version()").fetchone()[0]
            extension = connection.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
            database = connection.execute("SELECT current_database()").fetchone()[0]
        print(
            json.dumps(
                {
                    "engine": "postgresql",
                    "database": database,
                    "version": version,
                    "pgvector": extension[0] if extension else None,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, psycopg.Error, subprocess.CalledProcessError) as error:
        print(f"Database setup failed: {error}", file=sys.stderr)
        sys.exit(1)
