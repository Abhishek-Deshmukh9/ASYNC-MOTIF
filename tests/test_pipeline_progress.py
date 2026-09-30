import asyncio
import time

from fastapi.testclient import TestClient

from app.api.v1.endpoints import pipeline as pipeline_endpoint
from app.main import app


def _fake_pipeline(release: asyncio.Event):
    async def fake(progress=None, **kwargs):
        progress("clustering", 0, 10)
        progress("labelling", 1, 3)
        await release.wait()
        return {"status": "completed", "project_id": kwargs.get("project_id"), "duration_seconds": 1.5, "themes_created": 3}
    return fake


def test_background_run_reports_progress_then_result(monkeypatch):
    pipeline_endpoint._runs.clear()
    with TestClient(app) as client:
        release = asyncio.Event()
        monkeypatch.setattr(pipeline_endpoint, "run_ai_pipeline", _fake_pipeline(release))

        started = client.post("/api/v1/pipeline/run?background=true", json={})
        assert started.status_code == 200 and started.json()["status"] == "running"

        # a second start while one is running does not start another
        again = client.post("/api/v1/pipeline/run?background=true", json={})
        assert again.json()["already_running"] is True
        assert client.post("/api/v1/pipeline/run", json={}).status_code == 409

        deadline = time.time() + 3
        while time.time() < deadline:
            status = client.get("/api/v1/pipeline/status").json()
            if status["stage"] == "labelling":
                break
            time.sleep(0.05)
        assert status["status"] == "running" and (status["done"], status["total"]) == (1, 3)

        # finish the run from inside the app's event loop
        client.portal.call(release.set)
        deadline = time.time() + 3
        while time.time() < deadline and client.get("/api/v1/pipeline/status").json()["status"] == "running":
            time.sleep(0.05)
        final = client.get("/api/v1/pipeline/status").json()
        assert final["status"] == "idle"
        assert final["last_result"]["themes_created"] == 3


def test_failed_run_is_reported(monkeypatch):
    pipeline_endpoint._runs.clear()

    async def boom(progress=None, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(pipeline_endpoint, "run_ai_pipeline", boom)
    with TestClient(app) as client:
        assert client.post("/api/v1/pipeline/run", json={}).status_code == 500
        status = client.get("/api/v1/pipeline/status").json()
        assert status["status"] == "failed" and "model unavailable" in status["error"]
