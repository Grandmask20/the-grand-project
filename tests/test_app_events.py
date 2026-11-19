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
