import os
import tempfile
from fastapi.testclient import TestClient

os.environ.setdefault("BRIDGE_TOKEN", "test-token-that-is-long-enough-for-bridge-123456")
os.environ.setdefault("DOWNLOAD_ROOT", tempfile.mkdtemp(prefix="hazel-bridge-test-"))
os.environ.setdefault("STATE_PATH", os.path.join(tempfile.mkdtemp(prefix="hazel-bridge-state-test-"), "jobs.json"))

import app as bridge_app  # noqa: E402
from app import app, validate_magnet, Job, jobs, persist_jobs, restore_jobs, utc_now  # noqa: E402

client = TestClient(app)
HEADERS = {"Authorization": "Bearer " + os.environ["BRIDGE_TOKEN"]}


def test_health_is_public_and_minimal():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_job_endpoints_require_token():
    response = client.get("/api/v1/jobs")
    assert response.status_code == 401


def test_rejects_non_magnet_links():
    response = client.post(
        "/api/v1/jobs",
        headers=HEADERS,
        json={"magnet_uri": "https://example.com/file.torrent"},
    )
    assert response.status_code == 422


def test_rejects_magnet_without_info_hash():
    response = client.post(
        "/api/v1/jobs",
        headers=HEADERS,
        json={"magnet_uri": "magnet:?dn=missing-hash"},
    )
    assert response.status_code == 422


def test_validate_magnet_accepts_info_hash():
    value = "magnet:?xt=urn:btih:0123456789012345678901234567890123456789"
    assert validate_magnet(value) == value



def test_completed_job_metadata_survives_registry_reload(monkeypatch, tmp_path):
    state_path = tmp_path / "state" / "jobs.json"
    download_root = tmp_path / "downloads"
    monkeypatch.setattr(bridge_app, "STATE_PATH", state_path)
    monkeypatch.setattr(bridge_app, "DOWNLOAD_ROOT", download_root)
    jobs.clear()

    job_id = "a" * 32
    folder = download_root / job_id
    folder.mkdir(parents=True)
    (folder / "sample.bin").write_bytes(b"verified sample payload")
    now = utc_now()
    jobs[job_id] = Job(
        id=job_id,
        magnet_uri="magnet:?xt=urn:btih:0123456789012345678901234567890123456789",
        status="complete",
        created_at=now,
        updated_at=now,
        message="Download complete",
        return_code=0,
    )
    persist_jobs()

    jobs.clear()
    restore_jobs()

    assert jobs[job_id].status == "complete"
    assert jobs[job_id].message == "Download complete"
    assert bridge_app.job_response(jobs[job_id]).files == ["sample.bin"]


def test_interrupted_job_is_not_reported_as_downloading(monkeypatch, tmp_path):
    state_path = tmp_path / "state" / "jobs.json"
    monkeypatch.setattr(bridge_app, "STATE_PATH", state_path)
    monkeypatch.setattr(bridge_app, "DOWNLOAD_ROOT", tmp_path / "downloads")
    jobs.clear()
    now = utc_now()
    job_id = "b" * 32
    jobs[job_id] = Job(
        id=job_id,
        magnet_uri="magnet:?xt=urn:btih:0123456789012345678901234567890123456789",
        status="downloading",
        created_at=now,
        updated_at=now,
        message="Waiting for peers",
    )
    persist_jobs()

    jobs.clear()
    restore_jobs()

    assert jobs[job_id].status == "failed"
    assert "restarted" in jobs[job_id].message.lower()



def test_completed_file_can_be_downloaded_and_cancel_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge_app, "DOWNLOAD_ROOT", tmp_path / "downloads")
    monkeypatch.setattr(bridge_app, "STATE_PATH", tmp_path / "state" / "jobs.json")
    jobs.clear()
    job_id = "c" * 32
    folder = bridge_app.DOWNLOAD_ROOT / job_id
    folder.mkdir(parents=True)
    payload = b"example payload from completed job"
    (folder / "sample.bin").write_bytes(payload)
    now = utc_now()
    jobs[job_id] = Job(
        id=job_id,
        magnet_uri="magnet:?xt=urn:btih:0123456789012345678901234567890123456789",
        status="complete",
        created_at=now,
        updated_at=now,
        message="Download complete",
        return_code=0,
    )

    response = client.get(f"/api/v1/jobs/{job_id}/files/sample.bin", headers=HEADERS)
    assert response.status_code == 200
    assert response.content == payload

    cancelled = client.delete(f"/api/v1/jobs/{job_id}", headers=HEADERS)
    assert cancelled.status_code == 204
    assert jobs[job_id].status == "complete"
    assert bridge_app.job_response(jobs[job_id]).files == ["sample.bin"]
    jobs.clear()
