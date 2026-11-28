"""The adding worker (app.adding.AddingMixin): one job at a time from a queue fed by the page's request threads,
auto-add's batches, a switch refused while a job runs, closing, and detection in worker processes handed back.

Each test drives the real worker thread with a stand-in job (run_job) held on an Event where the order matters, so
what runs when is decided by the test, not by timing.
"""

import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from grand_project import builder, cities
from grand_project.app import constants as K
from grand_project.app.session import AtlasSession
from tests.test_atlas_owner import wait_until
from tests.webmap_data import make_atlas


@pytest.fixture
def two(tmp_path, monkeypatch):
    """Atlas A and atlas B; the locked stronghold search finds nothing (it reads screenshots these atlases lack)."""
    monkeypatch.setattr(cities, "find_locks", lambda atlas, todo: [])
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, _pts, _img = make_atlas(tmp_path / "a")
    b, _pts, _img = make_atlas(tmp_path / "b")
    return a, b


@pytest.fixture
def session(two, monkeypatch):
    """A session on atlas A, its worker not started yet (start_worker), screenshots accepted without the database."""
    s = AtlasSession(settings={}, worker=False)
    monkeypatch.setattr(s, "detector_ready", lambda: None)
    s.open_atlas(two[0])
    yield s
    s.shutdown()


def start_worker(s: AtlasSession) -> threading.Thread:
    t = threading.Thread(target=s._worker, daemon=True, name="adding")
    t.start()
    return t


class HeldJobs:
    """A stand-in for run_job: records each job and holds the first until `release` is set."""

    def __init__(self, hold_first: bool = True):
        self.ran: list[tuple[list[str], object]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.hold_first = hold_first
        self.working_inside: list[bool] = []

    def __call__(self, s: AtlasSession):
        def run_job(paths, mode):
            self.ran.append(([Path(p).name for p in paths], mode))
            self.working_inside.append(s.working())
            if len(self.ran) == 1 and self.hold_first:
                self.started.set()
                assert self.release.wait(10), "the test never let the first job end"

        return run_job


# ------------------------------------------------------------------ auto-add batches


def test_auto_add_jobs_waiting_together_run_as_one_batch_of_their_own_atlas(session, monkeypatch):
    jobs = HeldJobs(hold_first=False)
    monkeypatch.setattr(session, "run_job", jobs(session))
    q = session.events.listen()
    gen = session.generation
    for k in range(K.WATCH_BATCH + 6):  # more than one batch holds
        session._queue_job([f"w{k}.png"], "watch", gen)
    session._queue_job(["old.png"], "watch", gen - 1)  # a folder check made for the atlas open before
    session._queue_job(["x.png", "y.png"], "watch", gen)
    session._queue_job(["z.png"], "watch", gen)
    start_worker(session)
    assert wait_until(lambda: not session.working())
    sizes = [len(paths) for paths, _mode in jobs.ran]
    # a full batch, the rest up to the other atlas's job (never merged into it), that job skipped, then the last two
    assert sizes == [K.WATCH_BATCH, 6, 3]
    assert [p for paths, _m in jobs.ran for p in paths] == [f"w{k}.png" for k in range(K.WATCH_BATCH + 6)] + [
        "x.png",
        "y.png",
        "z.png",
    ]
    assert any("skipped a job queued for another atlas (watch)" in line for line in session.events.log_lines)
    assert session._jobs.unfinished_tasks == 0 and not session.working()
    busy = []
    while not q.empty():
        e = q.get_nowait()
        if e["kind"] == "busy":
            busy.append(e["data"])
    assert busy[-1] is False and busy.count(False) == 1  # idle said once, after the last job


# ------------------------------------------------------------------ the page's requests while a job runs


def test_adds_sent_at_once_while_a_job_runs_each_run_once_in_the_order_admitted(session, monkeypatch, rng, runs):
    jobs = HeldJobs()
    monkeypatch.setattr(session, "run_job", jobs(session))
    start_worker(session)
    session.add_screenshots(["first.png"])
    assert jobs.started.wait(10)
    senders = rng.randint(4, 12)
    start = threading.Barrier(senders)

    def send(k: int) -> None:
        start.wait(5)
        session.add_screenshots([f"s{k}.png"])

    threads = [threading.Thread(target=send, args=(k,)) for k in range(senders)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    admitted = [Path(job[0][0]).name for job in list(session._jobs.queue)]
    assert sorted(admitted) == sorted(f"s{k}.png" for k in range(senders))
    assert session.working()
    jobs.release.set()
    assert wait_until(lambda: not session.working())
    assert [paths[0] for paths, _mode in jobs.ran] == ["first.png", *admitted]  # each once, none lost, in order
    assert all(jobs.working_inside)  # (a job never ran while the app said it was idle)
    assert session._jobs.unfinished_tasks == 0


def test_another_atlas_is_not_opened_while_a_job_runs(session, two, monkeypatch):
    a, b = two
    jobs = HeldJobs()
    monkeypatch.setattr(session, "run_job", jobs(session))
    start_worker(session)
    session.add_screenshots(["first.png"])
    assert jobs.started.wait(10)
    refused: list[Exception] = []

    def switch() -> None:
        try:
            session.open_atlas(b)
        except ValueError as e:
            refused.append(e)

    t = threading.Thread(target=switch)  # (the page's request thread)
    t.start()
    t.join(10)
    assert refused and "being added" in str(refused[0])
    assert session.path == a
    jobs.release.set()
    assert wait_until(lambda: not session.working())
    session.open_atlas(b)  # once it is done
    assert session.path == b


def test_a_failing_auto_add_job_is_tried_again_and_the_worker_goes_on(session, monkeypatch):
    failed: list[list[str]] = []
    ran: list = []

    def run_job(paths, mode):
        ran.append(mode)
        if len(ran) <= 2:
            raise RuntimeError("detector crashed")

    monkeypatch.setattr(session, "run_job", run_job)
    monkeypatch.setattr(session, "_watch_failed", lambda paths: failed.append([Path(p).name for p in paths]))
    session._queue_job(["w.png"], "watch")
    session._queue_job(["m.png"], "manual")
    session._queue_job(["n.png"], "manual")
    start_worker(session)
    assert wait_until(lambda: not session.working())
    assert ran == ["watch", "manual", "manual"]  # the worker went on after both failures
    assert failed == [["w.png"]]  # only auto-add tries again by itself (a manual add is the player's to retry)
    assert sum("adding failed: detector crashed" in line for line in session.events.log_lines) == 2


# ------------------------------------------------------------------ closing


def test_no_job_is_started_once_closing_and_queued_ones_are_dropped(session):
    session._queue_job(["a.png"], "manual")
    session._queue_job(["b.png"], "manual")
    session._closing = True
    session._queue_job(["late.png"], "manual")
    assert [job[0] for job in session._jobs.queue] == [["a.png"], ["b.png"]]
    assert any("closing: 1 job(s) not started" in line for line in session.events.log_lines)
    session._drop_queued_jobs()
    assert session._jobs.unfinished_tasks == 0 and not session.working()
    session._closing = False


def test_closing_cuts_off_a_job_running_too_long_and_says_so(two, monkeypatch):
    s = AtlasSession(settings={}, worker=False)
    monkeypatch.setattr(s, "detector_ready", lambda: None)
    s.open_atlas(two[0])
    jobs = HeldJobs()
    monkeypatch.setattr(s, "run_job", jobs(s))
    monkeypatch.setattr(K, "SHUTDOWN_WAIT", 0.3)
    worker = start_worker(s)
    s.add_screenshots(["long.png"])
    assert jobs.started.wait(10)
    s.add_screenshots(["queued 1.png"])
    s.add_screenshots(["queued 2.png"])
    try:
        assert s.shutdown() is False  # (the job still runs: cut off, not reported as finished)
        assert any("was cut off" in line for line in s.events.log_lines)
        assert s._jobs.qsize() == 0  # the queued ones were dropped, never started
    finally:
        jobs.release.set()
    worker_idle = wait_until(lambda: not s.working())
    assert worker_idle and [paths for paths, _m in jobs.ran] == [["long.png"]]
    assert worker.is_alive()  # (a daemon: it ends with the app)


# ------------------------------------------------------------------ detection handed back by the worker processes


def test_a_screenshot_whose_worker_process_failed_is_detected_again_here(session, monkeypatch, caplog):
    shots = [Path("good.png"), Path("bad.png")]
    detected: list[str] = []

    def fake_uncached(paths, cache_dir, log=None, progress=None, pool=None):
        for k in range(1, len(paths) + 1):
            progress(k, len(paths))
        return {str(shots[1]): "RuntimeError('worker died')"}

    def extract(p, cache_dir):
        detected.append(p.name)
        return SimpleNamespace(usable=np.ones(3, bool), icons=[], path=str(p))

    monkeypatch.setattr(builder, "detect_uncached", fake_uncached)
    monkeypatch.setattr(builder, "extract_frame", extract)
    with caplog.at_level("WARNING"):
        frames, failed = session._detect(shots, "detecting")
    assert len(frames) == 2 and failed == []
    assert detected == ["good.png", "bad.png"]  # (read from the cache / detected again in this thread)
    assert "bad.png: detection failed in a worker" in caplog.text
    assert any("detecting 2 / 2" in line for line in session.events.log_lines)


def test_a_screenshot_that_cannot_be_detected_at_all_is_reported_failed(session, monkeypatch):
    shots = [Path("good.png"), Path("broken.png")]
    monkeypatch.setattr(builder, "detect_uncached", lambda paths, cache_dir, log=None, progress=None, pool=None: {})

    def extract(p, cache_dir):
        if p.name == "broken.png":
            raise ValueError("broken.png is not a readable image")
        return SimpleNamespace(usable=np.ones(2, bool), icons=[], path=str(p))

    monkeypatch.setattr(builder, "extract_frame", extract)
    frames, failed = session._detect(shots, "detecting")
    assert len(frames) == 1 and failed == ["broken.png"]
    assert any("broken.png: detection failed" in line for line in session.events.log_lines)


# ------------------------------------------------------------------ the session's warm detection pool


class PoolRecorder:
    """Stands in for builder.WarmPool: records how it is closed."""

    def __init__(self):
        self.closed: list[bool] = []

    def close(self, wait: bool = True) -> None:
        self.closed.append(wait)


def test_one_screenshot_goes_to_the_session_s_worker_processes_too(two, monkeypatch):
    s = AtlasSession(settings={}, worker=True)
    try:
        s.open_atlas(two[0])
        assert isinstance(s._detect_pool, builder.WarmPool) and not s._detect_pool.running()  # (none started yet)
        handed: list = []

        def uncached(paths, cache_dir, log=None, progress=None, pool=None):
            handed.append(([p.name for p in paths], pool))
            return {}

        monkeypatch.setattr(builder, "detect_uncached", uncached)
        monkeypatch.setattr(builder, "extract_frame", lambda p, d: SimpleNamespace(usable=np.ones(1, bool), icons=[]))
        frames, failed = s._detect([Path("one.png")], "detecting")
        assert handed == [(["one.png"], s._detect_pool)] and len(frames) == 1 and failed == []
    finally:
        s.shutdown()


def test_closing_closes_the_worker_processes_and_stops_them_when_a_job_is_cut_off(two, monkeypatch):
    s = AtlasSession(settings={}, worker=True)
    s.open_atlas(two[0])
    pool = s._detect_pool = PoolRecorder()
    assert s.shutdown() is True and pool.closed == [True]  # idle: they end by themselves

    s = AtlasSession(settings={}, worker=True)
    monkeypatch.setattr(s, "detector_ready", lambda: None)
    s.open_atlas(two[0])
    pool = s._detect_pool = PoolRecorder()
    jobs = HeldJobs()
    monkeypatch.setattr(s, "run_job", jobs(s))
    monkeypatch.setattr(K, "SHUTDOWN_WAIT", 0.3)
    s.add_screenshots(["long.png"])
    assert jobs.started.wait(10)
    try:
        assert s.shutdown() is False and pool.closed == [False]  # cut off: stopped, not waited for
    finally:
        jobs.release.set()


def test_a_session_without_its_worker_has_no_pool_and_detects_one_screenshot_itself(session, monkeypatch):
    assert session._detect_pool is None
    monkeypatch.setattr(builder, "detect_uncached", lambda *a, **k: pytest.fail("one screenshot sent to a pool"))
    monkeypatch.setattr(builder, "extract_frame", lambda p, d: SimpleNamespace(usable=np.ones(1, bool), icons=[]))
    assert len(session._detect([Path("one.png")], "detecting")[0]) == 1
