from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.workers.spawn import WindowsSpawnWorker
from rq.exceptions import InvalidJobOperation
from rq.job import JobStatus


def monitor(exit_code):
    worker = WindowsSpawnWorker.__new__(WindowsSpawnWorker)
    worker._horse = SimpleNamespace(poll=lambda: exit_code, returncode=exit_code)
    worker._horse_pid = 1234
    worker.set_current_job_working_time = Mock()
    worker.handle_job_failure = Mock()
    return worker


def test_successful_expired_job_does_not_query_deleted_status_or_stop_worker():
    worker = monitor(0)
    job = SimpleNamespace(get_status=Mock(side_effect=InvalidJobOperation("Job expired")))
    worker.monitor_work_horse(job, "documents")
    job.get_status.assert_not_called()
    worker.handle_job_failure.assert_not_called()
    assert worker._horse_pid == 0
    worker.set_current_job_working_time.assert_called_once_with(0)


def test_expired_job_after_abnormal_exit_is_not_recreated_as_failure():
    worker = monitor(1)
    job = SimpleNamespace(get_status=Mock(side_effect=InvalidJobOperation("Job expired")))
    worker.monitor_work_horse(job, "documents")
    worker.handle_job_failure.assert_not_called()


@pytest.mark.parametrize("status", [JobStatus.FINISHED, JobStatus.FAILED])
def test_terminal_job_is_not_failed_again(status):
    worker = monitor(1)
    job = SimpleNamespace(get_status=Mock(return_value=status))
    worker.monitor_work_horse(job, "documents")
    worker.handle_job_failure.assert_not_called()


def test_unexpected_child_exit_still_marks_incomplete_job_as_failed():
    worker = monitor(1)
    job = SimpleNamespace(get_status=Mock(return_value=JobStatus.STARTED))
    worker.monitor_work_horse(job, "documents")
    worker.handle_job_failure.assert_called_once_with(
        job, queue="documents", exc_string="Background process stopped before completion."
    )
