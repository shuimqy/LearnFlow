import argparse
import os

from redis import Redis
from rq import Queue
from rq.worker import SpawnWorker

from app.core.config import get_settings
from app.services.extraction_queue import QUEUE_NAME
from app.workers.spawn import WindowsSpawnWorker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--burst", action="store_true")
    parser.add_argument("--queue", default=QUEUE_NAME)
    args = parser.parse_args()
    connection = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
    worker_class = WindowsSpawnWorker if os.name == "nt" else SpawnWorker
    worker = worker_class([Queue(args.queue, connection=connection)], connection=connection)
    worker.work(burst=args.burst)


if __name__ == "__main__":
    main()
