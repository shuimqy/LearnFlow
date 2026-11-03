import os
import subprocess
import sys
import time

from rq.exceptions import InvalidJobOperation
from rq.job import JobStatus
from rq.worker import SpawnWorker


class WindowsSpawnWorker(SpawnWorker):
    # RQ 2.12 的 SpawnWorker 仍调用 setpgrp、wait4 和 killpg。
    def fork_work_horse(self, job, queue):
        self._horse = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.workers.horse",
                self.key,
                job.id,
                queue.name,
                self.execution.id,
            ],
            env=os.environ.copy(),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self._horse_pid = self._horse.pid

    def kill_horse(self, sig=None):
        if getattr(self, "_horse", None) and self._horse.poll() is None:
            self._horse.kill()

    def wait_for_horse(self):
        return self._horse.pid, self._horse.wait(), None

    def monitor_work_horse(self, job, queue):
        started = time.monotonic()
        while self._horse.poll() is None:
            try:
                self._horse.wait(timeout=self.job_monitoring_interval)
            except subprocess.TimeoutExpired:
                self.set_current_job_working_time(time.monotonic() - started)
                self.maintain_heartbeats(job)
                if job.timeout != -1 and time.monotonic() - started > job.timeout + 60:
                    self.kill_horse()
        self._horse_pid = 0
        self.set_current_job_working_time(0)
        if self._horse.returncode == 0:
            return
        try:
            status = job.get_status(refresh=True)
        except InvalidJobOperation:
            # result_ttl=0 的任务会由子进程在退出前删除。
            return
        if status not in {JobStatus.FINISHED, JobStatus.FAILED}:
            self.handle_job_failure(
                job, queue=queue, exc_string="Background process stopped before completion."
            )
