import os
import tempfile
from fastapi.testclient import TestClient

os.environ.setdefault("BRIDGE_TOKEN", "test-token-that-is-long-enough-for-bridge-123456")
os.environ.setdefault("DOWNLOAD_ROOT", tempfile.mkdtemp(prefix="hazel-bridge-test-"))

from app import app, validate_magnet  # noqa: E402

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
