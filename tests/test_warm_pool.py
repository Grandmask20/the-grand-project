"""builder.WarmPool: the viewer's detection worker processes, kept between jobs, closed when idle or the app closes,
and started again after a worker died. Real (spawned) processes: what is checked is which processes run."""

import os
import threading
import time
from concurrent.futures.process import BrokenProcessPool

import pytest

from grand_project import builder
from tests.test_atlas_owner import wait_until


@pytest.fixture
def pool():
    p = builder.WarmPool(2, idle_s=60.0)
    yield p
    p.close(wait=False)


def processes(ex) -> list:
    return list(ex._processes.values())  # (ProcessPoolExecutor's own: which processes it runs)


def pids(ex, n: int = 4) -> set[int]:
    return {f.result(timeout=120) for f in [ex.submit(os.getpid) for _ in range(n)]}


def test_jobs_reuse_the_same_worker_processes(pool):
    assert not pool.running()  # (nothing starts before the first job)
    with pool.use() as ex:
        ran = pids(ex)
        started = {p.pid for p in processes(ex)}  # (a process starts when a job needs it: one or both by now)
    assert pool.running() and ran <= started
    with pool.use() as ex2:
        assert ex2 is ex
        ran2 = pids(ex2)
        now = {p.pid for p in processes(ex2)}
    assert started <= now and ran2 <= now  # the first job's processes run the second: none started again
    assert all(p.is_alive() for p in processes(ex))
    assert os.getpid() not in ran | ran2  # (detected in the workers, not here)


def test_closing_ends_every_worker_process(pool):
    with pool.use() as ex:
        pids(ex)
        procs = processes(ex)
    assert procs
    pool.close()
    assert not any(p.is_alive() for p in procs)
    assert not pool.running()
    with pytest.raises(RuntimeError, match="closed"), pool.use():
        pass  # (the app is closing: no new job starts them again)


def test_the_workers_close_after_a_while_without_a_job_and_start_again_with_the_next():
    p = builder.WarmPool(1, idle_s=0.3)
    try:
        with p.use() as ex:
            first = pids(ex, 1)
            procs = processes(ex)
        assert wait_until(lambda: not p.running())
        assert wait_until(lambda: not any(proc.is_alive() for proc in procs))
        with p.use() as ex2:
            assert ex2 is not ex and pids(ex2, 1).isdisjoint(first)  # started again
    finally:
        p.close(wait=False)


def test_the_workers_are_kept_while_any_job_still_uses_them():
    p = builder.WarmPool(1, idle_s=0.2)
    holding, release = threading.Event(), threading.Event()

    def long_job() -> None:
        with p.use() as ex:
            pids(ex, 1)
            holding.set()
            release.wait(10)

    t = threading.Thread(target=long_job)
    t.start()
    try:
        assert holding.wait(60)
        with p.use() as ex:  # a second job ends while the first still runs
            pids(ex, 1)
        time.sleep(0.6)  # (three idle times: they would have closed had the second job's end started the clock)
        assert p.running()
    finally:
        release.set()
        t.join(10)
    assert wait_until(lambda: not p.running())  # the last job's end does
    p.close(wait=False)


def test_a_dead_worker_is_replaced_by_the_next_job(pool):
    with pool.use() as ex:
        pids(ex, 1)
        victim = processes(ex)[0]
    victim.kill()
    victim.join(10)
    with pytest.raises(BrokenProcessPool), pool.use() as ex:
        ex.submit(os.getpid).result(timeout=120)
    assert not pool.running()  # dropped
    with pool.use() as fresh:
        assert fresh is not ex and victim.pid not in pids(fresh, 2)


def test_closing_without_waiting_stops_a_job_still_running(pool):
    with pool.use() as ex:
        job = ex.submit(time.sleep, 120)
        procs = processes(ex)
        assert wait_until(job.running, 60)
    t0 = time.monotonic()
    pool.close(wait=False)  # (the app's close cut the job off)
    assert wait_until(lambda: not any(p.is_alive() for p in procs), 20)
    assert time.monotonic() - t0 < 20  # not the 120 s job's end
