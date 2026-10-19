import logging

from app.worker import Job, discover_jobs, run_safely


def test_job_discovery_returns_unique_job_objects():
    jobs = discover_jobs()
    assert all(isinstance(j, Job) for j in jobs)
    assert len({j.name for j in jobs}) == len(jobs)


def test_a_failing_job_is_logged_not_raised(caplog):
    def boom():
        raise RuntimeError("upstream site down")

    with caplog.at_level(logging.ERROR, logger="hishab.worker"):
        run_safely(Job(name="boom", func=boom))
    assert "job boom failed" in caplog.text


def test_a_successful_job_runs_once():
    calls = []
    run_safely(Job(name="ok", func=lambda: calls.append(1)))
    assert calls == [1]


def test_the_worker_entry_point_accepts_the_repos_real_jobs():
    # Runs exactly like the container (`python -m app.worker`), where the module is `__main__`:
    # a jobs module importing `Job` from `app.worker` must still pass discovery.
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "-m", "app.worker", "--list"], cwd=backend,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "security.anchor_audit_heads" in result.stdout
