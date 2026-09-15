import argparse
import os
import time
from datetime import datetime, timezone

from app import repository, services
from app.jobs import run_ingestion_locally
from app.queueing import enqueue_ingestion
from app.db import init_db


def run_cycle() -> int:
    init_db()
    count = 0
    resumed_goal_ids = set()
    for job in repository.list_unfinished_ingestion_jobs():
        queued = repository.mark_ingestion_queued(job["id"])
        if queued and not enqueue_ingestion(job["id"]):
            run_ingestion_locally(job["id"])
        resumed_goal_ids.add(job["goal_id"])
        count += 1
    for goal in repository.list_goals():
        if goal["status"] != "ACTIVE" or goal["id"] in resumed_goal_ids:
            continue
        bucket = datetime.now(timezone.utc).strftime("scheduler:%Y%m%d%H")
        job = services.start_recommendation_refresh(goal["id"], bucket)
        if job["status"] == "PENDING":
            repository.mark_ingestion_queued(job["id"])
            if not enqueue_ingestion(job["id"]):
                run_ingestion_locally(job["id"])
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Mission Control intelligence worker")
    parser.add_argument("--once", action="store_true", help="Run one ingestion cycle and exit")
    args = parser.parse_args()
    if args.once:
        run_cycle()
        return
    interval_seconds = max(900, int(os.getenv("INTELLIGENCE_INTERVAL_SECONDS", "21600")))
    while True:
        run_cycle()
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
