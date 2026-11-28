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
