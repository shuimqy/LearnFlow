import sys

from rq import Queue, Worker
from rq.executions import Execution
from rq.job import Job

from app.services.extraction_queue import redis_connection


def main():
    worker_key, job_id, queue_name, execution_id = sys.argv[1:]
    connection = redis_connection()
    worker = Worker.find_by_key(worker_key, connection=connection)
    if worker is None:
        sys.exit(1)
    job = Job.fetch(job_id, connection=connection)
    queue = Queue(queue_name, connection=connection)
    worker.execution = Execution.fetch(execution_id, job_id, connection=connection)
    worker.main_work_horse(job, queue)


if __name__ == "__main__":
    main()
