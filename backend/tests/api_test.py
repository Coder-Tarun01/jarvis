import os
import sys
import tempfile

_TEST_DATA = tempfile.mkdtemp(prefix="jarvis_api_test_")
os.environ["DATA_DIR"] = _TEST_DATA
os.environ["WORKSPACE_DIR"] = os.path.join(_TEST_DATA, "workspace")
os.environ["JARVIS_AUTH_TOKEN"] = "test-token"
os.environ["LLM_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

failures = []


def check(label, condition, extra=""):
    status = "ok  " if condition else "FAIL"
    print(f"[{status}] {label} {extra}")
    if not condition:
        failures.append(label)


with TestClient(app) as client:
    r = client.get("/healthz")
    check("GET /healthz", r.status_code == 200 and r.json()["status"] == "ok")

    r = client.get("/api/health")
    check("GET /api/health without token -> 401", r.status_code == 401)

    headers = {"Authorization": "Bearer test-token"}
    r = client.get("/api/health", headers=headers)
    body = r.json() if r.status_code == 200 else {}
    check("GET /api/health with token", r.status_code == 200 and body.get("status") == "ok")
    check("health reports tools", body.get("tool_count", 0) >= 20, f"({body.get('tool_count')})")
    check("health reports missing key", body.get("llm_configured") is False)
    check("health reports provider", body.get("provider") == "openai", str(body.get("provider")))
    check("health reports model", bool(body.get("model")), str(body.get("model")))
    check("health reports fast model", bool(body.get("model_fast")), str(body.get("model_fast")))

    r = client.get("/api/tools", headers=headers)
    check("GET /api/tools", r.status_code == 200 and len(r.json()) >= 20)

    r = client.post("/api/conversations", headers=headers, json={"title": "Smoke test"})
    check("POST /api/conversations", r.status_code == 201, str(r.status_code))
    conversation_id = r.json()["id"]

    r = client.get("/api/conversations", headers=headers)
    check("GET /api/conversations", r.status_code == 200 and any(c["id"] == conversation_id for c in r.json()))

    r = client.get(f"/api/conversations/{conversation_id}", headers=headers)
    check("GET /api/conversations/{id}", r.status_code == 200 and r.json()["messages"] == [])

    r = client.patch(f"/api/conversations/{conversation_id}", headers=headers, json={"title": "Renamed"})
    check("PATCH conversation", r.status_code == 200 and r.json()["title"] == "Renamed")

    r = client.get("/api/conversations", headers=headers, params={"q": "Renamed"})
    check("GET conversations?q=", r.status_code == 200 and len(r.json()) == 1)

    r = client.post("/api/tasks", headers=headers, json={"title": "Buy coffee", "when": "in 2 hours"})
    check("POST /api/tasks", r.status_code == 201, str(r.status_code))
    task_id = r.json()["id"]
    r = client.get("/api/tasks", headers=headers)
    check("GET /api/tasks", r.status_code == 200 and r.json()["count"] >= 1)
    r = client.patch(f"/api/tasks/{task_id}/complete", headers=headers)
    check("PATCH task complete", r.status_code == 200 and r.json()["status"] == "done")
    r = client.patch(f"/api/tasks/{task_id}/reopen", headers=headers)
    check("PATCH task reopen", r.status_code == 200 and r.json()["status"] == "open")
    r = client.delete(f"/api/tasks/{task_id}", headers=headers)
    check("DELETE task", r.status_code == 204)

    r = client.post("/api/notes", headers=headers, json={"title": "Wifi", "content": "password is hunter2"})
    check("POST /api/notes", r.status_code == 201)
    note_id = r.json()["id"]
    r = client.get("/api/notes", headers=headers, params={"q": "hunter2"})
    check(
        "GET /api/notes?q=",
        r.status_code == 200
        and r.json()["count"] >= 1
        and any("hunter2" in n["content"] for n in r.json()["notes"]),
    )
    r = client.get(f"/api/notes/{note_id}", headers=headers)
    check("GET /api/notes/{id}", r.status_code == 200)

    r = client.post("/api/memories", headers=headers, json={"text": "The user is allergic to peanuts."})
    check("POST /api/memories", r.status_code == 201)
    memory_id = r.json()["id"]
    r = client.get("/api/memories", headers=headers, params={"q": "peanuts"})
    check("GET /api/memories?q=", r.status_code == 200 and r.json()["count"] >= 1)
    r = client.delete(f"/api/memories/{memory_id}", headers=headers)
    check("DELETE memory", r.status_code == 204)

    r = client.post("/api/reminders", headers=headers, json={"text": "stretch", "when": "in 45 minutes"})
    check("POST /api/reminders", r.status_code == 201, str(r.status_code))
    reminder_id = r.json()["id"]
    r = client.get("/api/reminders", headers=headers)
    check("GET /api/reminders", r.status_code == 200 and r.json()["count"] >= 1)
    r = client.post("/api/reminders", headers=headers, json={"text": "past", "when": "2020-01-01T00:00"})
    check("POST past reminder -> 400", r.status_code == 400)
    r = client.delete(f"/api/reminders/{reminder_id}", headers=headers)
    check("DELETE reminder", r.status_code == 204)

    r = client.get("/api/speech/config", headers=headers)
    check("GET /api/speech/config", r.status_code == 200 and r.json()["stt_provider"] == "browser")

    try:
        with client.websocket_connect("/ws?token=wrong") as ws:
            ws.receive_json()
        check("WS rejects bad token", False)
    except Exception:
        check("WS rejects bad token", True)

    try:
        with client.websocket_connect("/ws?token=test-token") as ws:
            hello = ws.receive_json()
            check(
                "WS hello",
                hello.get("type") == "hello"
                and hello.get("llm_configured") is False
                and hello.get("provider") == "openai"
                and bool(hello.get("model")),
                str(hello)[:160],
            )
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            check("WS ping/pong", pong.get("type") == "pong")

            ws.send_json(
                {"type": "user_message", "text": "hello jarvis", "conversation_id": conversation_id}
            )
            seen = []
            for _ in range(10):
                event = ws.receive_json()
                seen.append(event.get("type"))
                if event.get("type") in ("error", "assistant_done"):
                    break
            check("WS conversation flow reports missing key", "error" in seen, str(seen))
    except Exception as exc:
        check("WS conversation flow", False, repr(exc))

    r = client.delete(f"/api/conversations/{conversation_id}", headers=headers)
    check("DELETE conversation", r.status_code == 204)

print("")
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("ALL API CHECKS PASSED")
