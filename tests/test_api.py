from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers import FakeLLM, make_docx

FIELDS = ["Full name", "Employee ID", "Department", "Leave type", "Start date", "End date", "Reason", "Manager"]


def handler(system: str, user: dict) -> dict:
    if "route a user's request" in system:
        leave = next(f for f in user["catalog"] if "Leave" in f["title"])
        return {"form_id": leave["id"], "reason": "You asked for time off."}
    if "extract form answers" in system:
        msg, ids = user["message"].lower(), {f["id"] for f in user["fields"]}
        known = {
            "Start date": ("friday", "2026-10-09"),
            "End date": ("friday", "2026-10-09"),
            "Full name": ("ana", "Ana Cruz"),
            "Employee ID": ("e-42", "E-42"),
            "Department": ("finance", "Finance"),
            "Leave type": ("vacation", "Vacation"),
            "Reason": ("trip", "Family trip"),
            "Manager": ("bea", "Bea Lim"),
        }
        return {"answers": {k: v for k, (kw, v) in known.items() if k in ids and kw in msg}, "skipped": []}
    return {"description": "Requesting leave / time off", "questions": {}}


def test_full_flow(tmp_path):
    client = TestClient(create_app(llm=FakeLLM(handler), data_dir=tmp_path))
    template = make_docx(*[f"{name}: {{{{{name}}}}}" for name in FIELDS])
    r = client.post("/api/forms/upload", files={"file": ("Leave Request.docx", template)})
    assert r.status_code == 200, r.text
    other = make_docx("Item: {{Item}}")
    client.post("/api/forms/upload", files={"file": ("Purchase.docx", other)})
    assert len(client.get("/api/forms").json()) == 2

    # The request already mentions the date, so those two aren't asked.
    turn = client.post("/api/chat", json={"message": "I need a leave this Friday"}).json()
    assert turn["stage"] == "asking"
    asked = [q["id"] for q in turn["questions"]]
    assert "Start date" not in asked and len(asked) == 6  # 6 remaining -> one batch

    turn = client.post(
        f"/api/chat/{turn['session_id']}", json={"message": "Ana, E-42, finance, vacation, family trip, manager is Bea"}
    ).json()
    assert turn["stage"] == "review" and turn["missing_required"] == []
    assert turn["action"] == "download"

    r = client.post(f"/api/chat/{turn['session_id']}/submit")
    assert r.status_code == 200
    text = [p.text for p in Document(BytesIO(r.content)).paragraphs]
    assert "Full name: Ana Cruz" in text and "Start date: 2026-10-09" in text

    # Session is gone after submitting: nothing kept.
    assert client.get(f"/api/chat/{turn['session_id']}/review").status_code == 404


def test_review_blocks_submit_until_required_filled(tmp_path):
    client = TestClient(create_app(llm=FakeLLM(handler), data_dir=tmp_path))
    client.post("/api/forms/upload", files={"file": ("Leave.docx", make_docx("{{Full name}} {{Manager}}"))})
    turn = client.post("/api/chat", json={"message": "leave please"}).json()
    sid = turn["session_id"]
    for _ in range(2):  # required fields get asked twice, then go to review
        turn = client.post(f"/api/chat/{sid}", json={"message": "no idea"}).json()
    assert turn["stage"] == "review" and set(turn["missing_required"]) == {"Full name", "Manager"}
    assert client.post(f"/api/chat/{sid}/submit").status_code == 422

    turn = client.put(f"/api/chat/{sid}/answers", json={"answers": {"Full name": "Ana", "Manager": "Bea"}}).json()
    assert turn["missing_required"] == []
    assert client.post(f"/api/chat/{sid}/submit").status_code == 200


def test_bad_upload(tmp_path):
    client = TestClient(create_app(llm=FakeLLM(handler), data_dir=tmp_path))
    r = client.post("/api/forms/upload", files={"file": ("x.txt", b"hi")})
    assert r.status_code == 422
    r = client.post("/api/forms/upload", files={"file": ("x.docx", make_docx("no blanks here"))})
    assert r.status_code == 422 and "{{" in r.json()["detail"]
