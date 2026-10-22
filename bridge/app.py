from __future__ import annotations

import asyncio
import hmac
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
BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "")
MAX_ACTIVE_JOBS = max(1, int(os.environ.get("MAX_ACTIVE_JOBS", "2")))
MAX_DOWNLOAD_GIB = max(1, int(os.environ.get("MAX_DOWNLOAD_GIB", "100")))
GIB = 1024**3
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")

app = FastAPI(title=APP_NAME, version="0.1.0")
jobs: dict[str, "Job"] = {}
job_tasks: dict[str, asyncio.Task] = {}
jobs_lock = asyncio.Lock()


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
    folder = job_dir(job.id)
    folder.mkdir(parents=True, exist_ok=True)
    job.status = "downloading"
    job.message = "Waiting for peers and downloading"
    job.updated_at = utc_now()
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
        else:
            job.status = "failed"
            detail = stderr.decode("utf-8", errors="replace").strip()
            job.message = (detail[-800:] if detail else f"aria2 exited with code {process.returncode}")
    except asyncio.CancelledError:
        job.status = "cancelled"
        job.message = "Cancelled"
        job.updated_at = utc_now()
        raise
    except Exception as exc:
        job.status = "failed"
        job.message = f"Download worker error: {type(exc).__name__}"
        job.updated_at = utc_now()


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
    return Response(status_code=204)
