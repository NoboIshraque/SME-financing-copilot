"""Background worker: runs scheduled jobs (WP-18).

Jobs are discovered like routers: any module `app/<area>/jobs.py` (or deeper) that defines
`JOBS: list[Job]` is scheduled. Examples: market price fetch (WP-09), alert scan (WP-04),
daily audit-chain anchor (WP-08/WP-11), nightly audit drill (WP-16). Times are Asia/Dhaka.

Run: `python -m app.worker` (the `worker` service in infra/docker-compose.yml).
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass, field

import app

log = logging.getLogger("hishab.worker")


@dataclass(frozen=True)
class Job:
    name: str
    func: Callable[[], object]
    cron: dict[str, str | int] = field(default_factory=dict)  # APScheduler cron fields


def discover_jobs() -> list[Job]:
    jobs: list[Job] = []
    for info in sorted(pkgutil.walk_packages(app.__path__, prefix="app."), key=lambda i: i.name):
        if not info.name.endswith(".jobs"):
            continue
        module = importlib.import_module(info.name)
        for job in getattr(module, "JOBS", []):
            if not isinstance(job, Job):
                raise TypeError(f"{info.name}.JOBS must contain Job objects")
            jobs.append(job)
    names = [j.name for j in jobs]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate job names: {sorted(names)}")
    return jobs


def run_safely(job: Job) -> None:
    """A failing job is logged and retried at its next slot; it never kills the worker."""
    try:
        job.func()
        log.info("job %s ok", job.name)
    except Exception:
        log.exception("job %s failed", job.name)


def main() -> None:  # pragma: no cover - long-running process
    from apscheduler.schedulers.blocking import BlockingScheduler

    from app.settings import get_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    scheduler = BlockingScheduler(timezone=get_settings().timezone)
    jobs = discover_jobs()
    for job in jobs:
        scheduler.add_job(run_safely, "cron", args=[job], id=job.name, coalesce=True,
                          max_instances=1, misfire_grace_time=600, **job.cron)
    log.info("worker started with %d jobs: %s", len(jobs), ", ".join(j.name for j in jobs))
    scheduler.start()


if __name__ == "__main__":  # pragma: no cover
    main()
