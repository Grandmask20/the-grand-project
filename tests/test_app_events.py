"""What the app tells the page (app.events.Events): events, the log, progress, and yes / no questions."""

import json
import threading

from grand_project.app.events import Events, sse


def test_events_reach_every_listener_and_the_history():
    ev = Events()
    a, b = ev.listen(), ev.listen()
    ev.publish("model", 3)
    assert a.get_nowait()["data"] == 3 and b.get_nowait()["kind"] == "model"
    ev.stop_listening(b)
    ev.log("hello")
    assert a.get_nowait()["kind"] == "log" and b.empty()
    assert ev.log_lines[-1].endswith("  hello") and ev.history[-1]["kind"] == "log"


def test_progress_and_status_are_kept_for_a_page_opened_later():
    ev = Events()
    ev.set_progress("placing")
    ev.set_status("added 2")
    assert (ev.progress, ev.status) == ("placing", "added 2")
    ev.set_progress(None)
    assert ev.progress is None


def test_a_question_waits_for_the_page_and_is_no_without_one():
    ev = Events()
    assert ev.ask("anyone?") is False  # no page open: nothing is added that nobody saw
    q = ev.listen()
    got = {}
    t = threading.Thread(
        target=lambda: got.setdefault("yes", ev.ask("Add it?", preview={"picture": 1, "box": [0, 0, 1, 1]}))
    )
    t.start()
    asked = q.get(timeout=5)
    assert asked["kind"] == "question" and asked["data"]["question"] == "Add it?"
    assert ev.open_questions()[0]["preview"]["picture"] == 1
    assert ev.answer(asked["data"]["id"], True)
    t.join(5)
    assert got["yes"] is True and not ev.open_questions()
    assert not ev.answer(999, True)


def test_sse_lines():
    raw = sse({"id": 4, "kind": "status", "data": {"a": 1}}).decode()
    assert raw == f"id: 4\nevent: status\ndata: {json.dumps({'a': 1})}\n\n"


def test_progress_steps_reach_the_log_each_new_step_and_every_tenth():
    ev = Events()
    ev.set_progress("placing")
    for i in range(1, 501):
        ev.set_progress(f"fixing seams {i} / 500")
    ev.set_progress(None)
    lines = [line.split("  ", 1)[1] for line in ev.log_lines]
    assert lines[0] == "placing"  # (user: "it should list ongoing processes")
    seams = [line for line in lines if line.startswith("fixing seams")]
    assert seams[0] == "fixing seams 1 / 500" and seams[-1] == "fixing seams 500 / 500" and len(seams) == 11


def test_two_jobs_reporting_at_once_log_each_step_once():
    ev = Events()
    for i in range(1, 11):  # adding and Fix seams interleaved
        ev.set_progress(f"adding {i} / 10")
        ev.set_progress("fixing seams: building the clean map...")
    lines = [line.split("  ", 1)[1] for line in ev.log_lines]
    assert lines.count("fixing seams: building the clean map...") == 1 and len(lines) == 11


def test_the_same_progress_step_reaches_each_atlas_log_once():
    ev = Events()
    for _ in range(3):
        ev.set_progress("fixing seams 1 / 500", scope="a.json")
        ev.set_progress("fixing seams 1 / 500", scope="b.json")
    lines = [entry["data"]["scope"] for entry in ev.history if entry["kind"] == "log"]
    assert lines == ["a.json", "b.json"]  # one in each atlas's log (one was skipped: CodeRabbit), no repeats


def test_a_yes_coming_in_as_the_app_closes_never_undoes_its_no():
    # (CodeRabbit: an answer racing the close could turn its No into a Yes)
    import queue
    import threading

    from grand_project.app.events import Events

    ev = Events()
    ev._listeners.append(queue.Queue())
    got = []
    t = threading.Thread(target=lambda: got.append(ev.ask("go on?")))
    t.start()
    for _ in range(200):
        if ev.open_questions():
            break
        threading.Event().wait(0.01)
    qid = ev.open_questions()[0]["id"]
    assert ev.end_questions() == 1
    assert ev.answer(qid, True) is False  # (too late: closing)
    t.join(2)
    assert got == [False]


# ------------------------------------------------------------------ several threads publishing at once


class _FirstIdHeld:
    """An event id source that hands out id 1 only once `go` is set: the first publisher pauses right after taking its
    id, while another thread publishes."""

    def __init__(self):
        self._ids = iter(range(1, 10**6))
        self.taken = threading.Event()
        self.go = threading.Event()

    def __iter__(self):
        return self

    def __next__(self) -> int:
        n = next(self._ids)
        if n == 1:
            self.taken.set()
            self.go.wait(5)
        return n


def test_events_reach_the_history_in_the_order_of_their_ids():
    # the id was taken outside the lock: a publisher paused between taking id 1 and appending let id 2 in first, so
    # the history (what a reconnecting page replays) went 2, 1
    ev = Events()
    ids = ev._ids = _FirstIdHeld()
    q = ev.listen()
    first = threading.Thread(target=ev.publish, args=("model", "first"))
    first.start()
    assert ids.taken.wait(5)
    second = threading.Thread(target=ev.publish, args=("model", "second"))
    second.start()
    second.join(0.3)  # (it waits for the first publisher now, or it was already through: the old order)
    ids.go.set()
    first.join(5)
    second.join(5)
    assert [e["id"] for e in ev.history] == [1, 2]
    assert [q.get_nowait()["data"] for _ in range(2)] == ["first", "second"]


def test_many_threads_publishing_lose_nothing_and_keep_the_id_order(rng, runs):
    for _ in range(runs(5)):
        ev = Events()
        listener = ev.listen()
        threads, each = rng.randint(2, 8), rng.randint(5, 20)
        start = threading.Barrier(threads)

        def publish(t: int, ev=ev, start=start, each=each) -> None:
            start.wait(5)
            for i in range(each):
                ev.publish("model", (t, i))

        workers = [threading.Thread(target=publish, args=(t,)) for t in range(threads)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(10)
        got = [listener.get_nowait() for _ in range(threads * each)]
        assert listener.empty()
        assert [e["id"] for e in got] == sorted(e["id"] for e in got) == list(range(1, threads * each + 1))
        assert [e["id"] for e in ev.history] == sorted(e["id"] for e in ev.history)
        for t in range(threads):  # each thread's own events in the order it published them
            assert [e["data"][1] for e in got if e["data"][0] == t] == list(range(each))


def test_jobs_reporting_progress_from_their_own_threads_leave_the_box_as_last_published():
    ev = Events()
    owners = ["job", "map1", "seams"]
    start = threading.Barrier(len(owners))

    def report(owner: str) -> None:
        start.wait(5)
        for i in range(1, 11):
            ev.set_progress(f"{owner} step {i} / 10", owner=owner)
        if owner != "seams":
            ev.set_progress(None, owner=owner)

    workers = [threading.Thread(target=report, args=(o,)) for o in owners]
    for w in workers:
        w.start()
    for w in workers:
        w.join(10)
    shown = [e["data"] for e in ev.history if e["kind"] == "progress"]
    assert ev.progress == shown[-1] == "seams step 10 / 10"  # (the box the page keeps is the one published last)
    lines = [line.split("  ", 1)[1] for line in ev.log_lines]
    for owner in owners:  # every tenth of each job's step once, whichever thread came first
        assert [ln for ln in lines if ln.startswith(owner)] == [f"{owner} step {i} / 10" for i in range(1, 11)]
