from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

APP_NAME = "PC-Free Hazel HTTP Bridge"
DOWNLOAD_ROOT = Path(os.environ.get("DOWNLOAD_ROOT", "/downloads")).resolve()
STATE_PATH = Path(os.environ.get("STATE_PATH", "/state/jobs.json")).resolve()
BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "")
MAX_ACTIVE_JOBS = max(1, int(os.environ.get("MAX_ACTIVE_JOBS", "2")))
MAX_DOWNLOAD_GIB = max(1, int(os.environ.get("MAX_DOWNLOAD_GIB", "100")))
GIB = 1024**3
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")

app = FastAPI(title=APP_NAME, version="0.1.0")
jobs: dict[str, "Job"] = {}
job_tasks: dict[str, asyncio.Task] = {}
jobs_lock = asyncio.Lock()


def persist_jobs() -> None:
    """Atomically persist job metadata; downloaded payloads remain in DOWNLOAD_ROOT."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(job) for job in jobs.values()]
    temporary = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def restore_jobs() -> None:
    """Restore history and mark interrupted transfers rather than claiming they are active."""
    if not STATE_PATH.is_file():
        return
    try:
        records = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("state root must be a list")
        restored: dict[str, Job] = {}
        for record in records:
            if not isinstance(record, dict) or not JOB_ID_RE.fullmatch(str(record.get("id", ""))):
                continue
            status = record.get("status")
            if status not in {"queued", "downloading", "complete", "failed", "cancelled"}:
                continue
            job = Job(
                id=record["id"],
                magnet_uri=str(record.get("magnet_uri", "")),
                status=status,
                created_at=str(record.get("created_at", utc_now())),
                updated_at=str(record.get("updated_at", utc_now())),
                message=str(record.get("message", "")),
                return_code=record.get("return_code") if isinstance(record.get("return_code"), int) else None,
            )
            if job.status in {"queued", "downloading"}:
                job.status = "failed"
                job.message = "Bridge restarted during this transfer. Submit the magnet again to resume."
                job.updated_at = utc_now()
            if job.status == "complete" and not list_files(job.id):
                job.status = "failed"
                job.message = "Completed payload is missing from bridge storage."
                job.updated_at = utc_now()
            restored[job.id] = job
        jobs.clear()
        jobs.update(restored)
        persist_jobs()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        # A damaged state file must not prevent the API from starting. Preserve it for
        # inspection, but start with an empty registry rather than trusting malformed data.
        jobs.clear()


@app.on_event("startup")
async def load_persisted_jobs() -> None:
    restore_jobs()


@dataclass
class Job:
    id: str
    magnet_uri: str
    status: Literal["queued", "downloading", "complete", "failed", "cancelled"]
    created_at: str
    updated_at: str
    message: str = "Queued"
    return_code: int | None = None


class CreateJobRequest(BaseModel):
    magnet_uri: str = Field(min_length=20, max_length=8192)


class JobResponse(BaseModel):
    id: str
    status: str
    created_at: str
    updated_at: str
    message: str
    files: list[str] = []


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_configured_token() -> None:
    if len(BRIDGE_TOKEN) < 32:
        raise HTTPException(
            status_code=503,
            detail="Bridge is not configured. Set BRIDGE_TOKEN to a random secret of at least 32 characters.",
        )


async def authorize(authorization: str | None = Header(default=None)) -> None:
    require_configured_token()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    supplied = authorization[7:].strip()
    if not hmac.compare_digest(supplied, BRIDGE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")


def validate_magnet(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme.lower() != "magnet" or not parsed.query:
        raise HTTPException(status_code=422, detail="Only magnet: links are accepted")
    if not any(part.startswith("xt=urn:btih:") or part.startswith("xt=urn:btmh:") for part in parsed.query.split("&")):
        raise HTTPException(status_code=422, detail="Magnet link must contain a BitTorrent info hash")
    return value


def job_dir(job_id: str) -> Path:
    if not JOB_ID_RE.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    path = (DOWNLOAD_ROOT / job_id).resolve()
    if path.parent != DOWNLOAD_ROOT:
        raise HTTPException(status_code=404, detail="Job not found")
    return path


def list_files(job_id: str) -> list[str]:
    root = job_dir(job_id)
    if not root.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not p.name.endswith(".aria2"))


def job_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        message=job.message,
        files=list_files(job.id) if job.status == "complete" else [],
    )


async def run_aria2(job: Job) -> None:
    process: asyncio.subprocess.Process | None = None
    folder = job_dir(job.id)
    folder.mkdir(parents=True, exist_ok=True)
    job.status = "downloading"
    job.message = "Waiting for peers and downloading"
    job.updated_at = utc_now()
    persist_jobs()
    # Do not enable RPC or seed after completion. A single job gets its own folder.
    command = [
        "aria2c",
        "--dir", str(folder),
        "--seed-time=0",
        "--follow-torrent=mem",
        "--bt-save-metadata=true",
        "--summary-interval=0",
        "--console-log-level=warn",
        "--download-result=hide",
        "--max-tries=5",
        "--retry-wait=5",
        "--connect-timeout=20",
        "--timeout=60",
        job.magnet_uri,
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        job.return_code = process.returncode
        job.updated_at = utc_now()
        if process.returncode == 0 and list_files(job.id):
            job.status = "complete"
            job.message = "Download complete"
            persist_jobs()
        else:
            job.status = "failed"
            detail = stderr.decode("utf-8", errors="replace").strip()
            job.message = (detail[-800:] if detail else f"aria2 exited with code {process.returncode}")
            persist_jobs()
    except asyncio.CancelledError:
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        job.status = "cancelled"
        job.message = "Cancelled"
        job.updated_at = utc_now()
        persist_jobs()
        raise
    except Exception as exc:
        job.status = "failed"
        job.message = f"Download worker error: {type(exc).__name__}"
        job.updated_at = utc_now()
        persist_jobs()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": APP_NAME, "version": "0.1.0"}


@app.post("/api/v1/jobs", response_model=JobResponse, status_code=202, dependencies=[Depends(authorize)])
async def create_job(request: CreateJobRequest) -> JobResponse:
    magnet = validate_magnet(request.magnet_uri)
    async with jobs_lock:
        active = sum(job.status in {"queued", "downloading"} for job in jobs.values())
        if active >= MAX_ACTIVE_JOBS:
            raise HTTPException(status_code=429, detail="Active download limit reached")
        # Best-effort disk quota guard before accepting another job.
        used = sum(p.stat().st_size for p in DOWNLOAD_ROOT.rglob("*") if p.is_file())
        if used >= MAX_DOWNLOAD_GIB * GIB:
            raise HTTPException(status_code=507, detail="Bridge storage quota reached")
        DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        now = utc_now()
        job = Job(id=job_id, magnet_uri=magnet, status="queued", created_at=now, updated_at=now)
        jobs[job_id] = job
        persist_jobs()
        job_tasks[job_id] = asyncio.create_task(run_aria2(job))
        return job_response(job)


@app.get("/api/v1/jobs", response_model=list[JobResponse], dependencies=[Depends(authorize)])
async def get_jobs() -> list[JobResponse]:
    return [job_response(job) for job in sorted(jobs.values(), key=lambda item: item.created_at, reverse=True)]


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(authorize)])
async def get_job(job_id: str) -> JobResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (jobs are held in memory until the bridge restarts)")
    return job_response(job)


@app.get("/api/v1/jobs/{job_id}/files/{file_path:path}", dependencies=[Depends(authorize)])
async def download_file(job_id: str, file_path: str, response: Response):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "complete":
        raise HTTPException(status_code=409, detail="Download is not complete")
    root = job_dir(job_id)
    candidate = (root / file_path).resolve()
    if root not in candidate.parents or not candidate.is_file() or candidate.name.endswith(".aria2"):
        raise HTTPException(status_code=404, detail="File not found")
    response.headers["Cache-Control"] = "no-store"
    return FileResponse(candidate, filename=candidate.name, content_disposition_type="attachment")


@app.delete("/api/v1/jobs/{job_id}", status_code=204, dependencies=[Depends(authorize)])
async def cancel_job(job_id: str) -> Response:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Cancellation is idempotent, but it must not hide an already-completed result or
    # rewrite a previous failure into a cancellation.
    if job.status not in {"queued", "downloading"}:
        return Response(status_code=204)
    task = job_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    job.status = "cancelled"
    job.message = "Cancelled by user"
    job.updated_at = utc_now()
    persist_jobs()
    return Response(status_code=204)
