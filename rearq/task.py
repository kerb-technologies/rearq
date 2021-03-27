import datetime
from typing import Any, Callable, Dict, Optional, Tuple, Union
from uuid import uuid4

from crontab import CronTab
from loguru import logger
from tortoise import timezone

from rearq.constants import DELAY_QUEUE
from rearq.job import JobStatus
from rearq.server.models import Job
from rearq.utils import timestamp_ms_now, to_ms_timestamp


class Task:
    def __init__(
        self,
        bind: bool,
        function: Callable,
        queue: str,
        rearq,
        job_retry: int,
        job_retry_after: int,
    ):

        self.job_retry = job_retry
        self.job_retry_after = job_retry_after
        self.queue = queue
        self.rearq = rearq
        self.function = function
        self.bind = bind

    async def delay(
        self,
        args: Optional[Tuple[Any, ...]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        job_id: str = None,
        countdown: Union[float, datetime.timedelta] = 0,
        eta: Optional[datetime.datetime] = None,
        job_retry: int = 0,
        job_retry_after: int = 60,
    ) -> Job:
        if not job_id:
            job_id = uuid4().hex
        if countdown:
            defer_ts = to_ms_timestamp(countdown)
        elif eta:
            defer_ts = to_ms_timestamp(eta)
        else:
            defer_ts = timestamp_ms_now()

        job = await Job.get_or_none(job_id=job_id)
        if job:
            logger.warning(f"Job {job_id} exists")
            return job

        job = Job(
            task=self.function.__name__,
            args=args,
            kwargs=kwargs,
            job_retry=job_retry or self.job_retry,
            queue=self.queue,
            job_id=job_id,
            enqueue_time=timezone.now(),
            job_retry_after=job_retry_after,
        )

        if not eta and not countdown:
            job.status = JobStatus.queued
            await job.save()
            await self.rearq.redis.xadd(self.queue, {"job_id": job_id})
        else:
            job.status = JobStatus.deferred
            await job.save()
            await self.rearq.redis.zadd(DELAY_QUEUE, defer_ts, f"{self.queue}:{job_id}")

        return job


async def check_pending_msgs(
    self: Task, queue: str, group_name: str, consumer_name: str, timeout: int
):
    """
    check pending messages
    :return:
    """
    redis = self.rearq.redis
    pending_msgs = await redis.xpending(self.queue, group_name, "-", "+", 10)
    p = redis.pipeline()
    execute = False
    for msg in pending_msgs:
        msg_id, _, idle_time, times = msg
        if int(idle_time / 1000) > timeout * 2:
            execute = True
            p.xclaim(queue, group_name, consumer_name, min_idle_time=1000, id=msg_id)
    if execute:
        return await p.execute()


class CronTask(Task):
    _cron_tasks: Dict[str, "CronTask"] = {}
    next_run: int

    def __init__(
        self,
        bind: bool,
        function: Callable,
        queue: str,
        rearq,
        job_retry: int,
        job_retry_after: int,
        cron: str,
    ):
        super().__init__(bind, function, queue, rearq, job_retry, job_retry_after)
        self.crontab = CronTab(cron)
        self.cron = cron
        self.set_next()

    def set_next(self):
        self.next_run = to_ms_timestamp(self.crontab.next(default_utc=False))

    @classmethod
    def add_cron_task(cls, function: str, cron_task: "CronTask"):
        cls._cron_tasks[function] = cron_task

    @classmethod
    def get_cron_tasks(cls):
        return cls._cron_tasks
