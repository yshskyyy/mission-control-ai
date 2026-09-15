from redis import Redis
from redis.exceptions import RedisError
from rq import Queue, Retry

from app.config import settings


QUEUE_NAME = "mission-control"
MAX_ATTEMPTS = 3


class QueueUnavailableError(RuntimeError):
    pass


def _is_production() -> bool:
    return str(getattr(settings, "environment", "development")).lower() == "production"


def enqueue_ingestion(job_id: str) -> bool:
    redis_url = getattr(settings, "redis_url", None)
    if not redis_url:
        if _is_production():
            raise QueueUnavailableError("REDIS_URL is required in production")
        return False
    try:
        connection = Redis.from_url(redis_url)
        connection.ping()
        Queue(QUEUE_NAME, connection=connection).enqueue(
            "app.jobs.run_ingestion", job_id,
            job_id=f"ingestion-{job_id}", job_timeout=900,
            retry=Retry(max=MAX_ATTEMPTS - 1, interval=[10, 30]),
            result_ttl=86400, failure_ttl=604800,
        )
        return True
    except RedisError as exc:
        if _is_production():
            raise QueueUnavailableError("Redis/RQ is unavailable") from exc
        return False
