from app import repository, services
from app.queueing import MAX_ATTEMPTS


def run_ingestion(job_id: str) -> None:
    job = repository.start_ingestion_attempt(job_id)
    if not job:
        current = repository.get_ingestion_job(job_id)
        if current and current["status"] == "SUCCEEDED":
            return
        raise RuntimeError(f"Ingestion job {job_id} is not QUEUED")
    try:
        services.refresh_recommendations(job_id)
    except Exception as exc:
        error = str(exc)[:500]
        if job["attempt_count"] >= job["max_attempts"]:
            repository.mark_ingestion_failed(job_id, error)
        else:
            repository.mark_ingestion_retryable(job_id, error)
        raise


def run_ingestion_locally(job_id: str) -> None:
    """Bounded local fallback with the same three-attempt state machine as RQ."""
    for _ in range(MAX_ATTEMPTS):
        try:
            run_ingestion(job_id)
            return
        except Exception:
            job = repository.get_ingestion_job(job_id)
            if not job or job["status"] == "FAILED":
                return
            if job["status"] != "QUEUED":
                raise
    raise RuntimeError(f"Ingestion job {job_id} exceeded the local retry bound")
