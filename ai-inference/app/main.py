"""
ai-inference — FastAPI service for simulated DICOM AI inference.

Endpoints:
  POST /infer                — synchronous inference (returns JSON results immediately)
  GET  /infer/{job_id}       — poll async job status (for long-running model support)
  GET  /health               — liveness probe

Inference simulation:
  For each instance UID supplied, we compute a circular ROI centred on the
  image frame. In a real deployment this would load an ONNX model via
  onnxruntime.InferenceSession and run pixel-level segmentation.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import time
import uuid
from typing import Any, Optional

import numpy as np
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Optional: onnxruntime for real model inference
try:
    import onnxruntime as ort  # type: ignore
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

# Optional: minio for result storage
try:
    from minio import Minio  # type: ignore
    from minio.error import S3Error  # type: ignore
    MINIO_AVAILABLE = True
except ImportError:
    MINIO_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Inference Service",
    description="Simulated DICOM AI inference — ROI detection",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store (replace with Redis or Postgres in production)
_jobs: dict[str, dict[str, Any]] = {}

# MinIO client — initialised lazily
_minio_client: Optional[Any] = None


def get_minio_client() -> Optional[Any]:
    global _minio_client
    if not MINIO_AVAILABLE:
        return None
    if _minio_client is None:
        endpoint = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
        # Strip scheme for minio client
        endpoint_host = endpoint.replace("http://", "").replace("https://", "")
        secure = endpoint.startswith("https://")
        try:
            _minio_client = Minio(
                endpoint_host,
                access_key=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
                secret_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin123"),
                secure=secure,
            )
        except Exception as exc:
            logger.warning("Could not initialise MinIO client: %s", exc)
    return _minio_client


# ── Pydantic models ───────────────────────────────────────────────────────────

class InferRequest(BaseModel):
    study_uid: str
    series_uid: str
    instance_uids: list[str]


class MaskResult(BaseModel):
    instance_uid: str
    rows: int
    cols: int
    mask: dict[str, Any]  # {cx, cy, r, label, confidence}


class InferResponse(BaseModel):
    job_id: str
    study_uid: str
    series_uid: str
    results: list[MaskResult]
    processing_time_ms: float


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # PENDING | RUNNING | DONE | FAILED
    result_url: Optional[str] = None
    error: Optional[str] = None


# ── Core inference logic ──────────────────────────────────────────────────────

def _simulate_roi_detection(
    instance_uid: str,
    rows: int = 512,
    cols: int = 512,
) -> MaskResult:
    """
    Simulated detection pipeline:

    1. (Real pipeline) Load DICOM pixel array via pydicom
    2. (Real pipeline) Pre-process: normalise HU to [0,1], resize to model input
    3. (Real pipeline) Run onnxruntime session.run(...)
    4. Post-process: threshold probability map, extract largest connected component

    Simulation: place a circular ROI at the image centre with a radius
    proportional to the shorter image dimension. A small random jitter makes
    it look like real detection across multiple instances.
    """
    rng = np.random.default_rng(seed=abs(hash(instance_uid)) % (2**32))

    # Jitter centre by ±5% of image dimensions
    jitter_y = int(rng.uniform(-0.05, 0.05) * rows)
    jitter_x = int(rng.uniform(-0.05, 0.05) * cols)

    cx = cols // 2 + jitter_x
    cy = rows // 2 + jitter_y

    # Radius: ~12% of shorter dimension
    r = int(min(rows, cols) * 0.12)

    # Simulate a probability map (numpy) — in reality this comes from the model
    prob_map = np.zeros((rows, cols), dtype=np.float32)
    y_coords, x_coords = np.ogrid[:rows, :cols]
    dist = np.sqrt((x_coords - cx) ** 2 + (y_coords - cy) ** 2)
    within_circle = dist <= r
    prob_map[within_circle] = rng.uniform(0.75, 0.98, size=within_circle.sum()).astype(np.float32)

    max_prob = float(prob_map.max())
    confidence = round(max_prob, 4)

    label = "Nodule candidate" if confidence > 0.80 else "Low-confidence finding"

    return MaskResult(
        instance_uid=instance_uid,
        rows=rows,
        cols=cols,
        mask={
            "cx": cx,
            "cy": cy,
            "r": r,
            "label": label,
            "confidence": confidence,
            "type": "circle",
        },
    )


def _run_inference_task(job_id: str, request: InferRequest) -> None:
    """Background task: run inference and update job state."""
    _jobs[job_id]["status"] = "RUNNING"
    t0 = time.perf_counter()

    try:
        results: list[MaskResult] = []

        for uid in request.instance_uids:
            # Default 512x512; a real implementation would read from pydicom dataset
            result = _simulate_roi_detection(uid, rows=512, cols=512)
            results.append(result)
            logger.info(
                "Processed instance %s → mask cx=%d cy=%d r=%d confidence=%.3f",
                uid,
                result.mask["cx"],
                result.mask["cy"],
                result.mask["r"],
                result.mask["confidence"],
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        response_data = InferResponse(
            job_id=job_id,
            study_uid=request.study_uid,
            series_uid=request.series_uid,
            results=results,
            processing_time_ms=round(elapsed_ms, 2),
        )

        _jobs[job_id]["status"] = "DONE"
        _jobs[job_id]["result"] = response_data.model_dump()

        # Optionally persist to MinIO
        _store_result_minio(job_id, response_data)

    except Exception as exc:
        logger.exception("Inference failed for job %s", job_id)
        _jobs[job_id]["status"] = "FAILED"
        _jobs[job_id]["error"] = str(exc)


def _store_result_minio(job_id: str, response: InferResponse) -> None:
    """Persist inference result JSON to MinIO (best-effort)."""
    client = get_minio_client()
    if client is None:
        return

    bucket = os.environ.get("MINIO_BUCKET", "ai-results")
    object_name = f"results/{job_id}.json"
    payload = response.model_dump_json().encode("utf-8")

    try:
        found = client.bucket_exists(bucket)
        if not found:
            client.make_bucket(bucket)

        client.put_object(
            bucket,
            object_name,
            io.BytesIO(payload),
            length=len(payload),
            content_type="application/json",
        )
        logger.info("Stored result in MinIO: %s/%s", bucket, object_name)
    except Exception as exc:
        logger.warning("MinIO store failed: %s", exc)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "onnx_available": str(ONNX_AVAILABLE),
        "minio_available": str(MINIO_AVAILABLE),
    }


@app.post("/infer", response_model=InferResponse)
def infer_sync(request: InferRequest) -> InferResponse:
    """
    Synchronous inference — processes all instances and returns results immediately.

    The imaging-api calls this endpoint in its @Async thread, so blocking here
    is acceptable. For very long models, switch to the async /infer/{job_id} flow.
    """
    if not request.instance_uids:
        raise HTTPException(status_code=400, detail="instance_uids must not be empty")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "RUNNING"}

    t0 = time.perf_counter()
    results: list[MaskResult] = []

    for uid in request.instance_uids:
        results.append(_simulate_roi_detection(uid, rows=512, cols=512))

    elapsed_ms = (time.perf_counter() - t0) * 1000

    response = InferResponse(
        job_id=job_id,
        study_uid=request.study_uid,
        series_uid=request.series_uid,
        results=results,
        processing_time_ms=round(elapsed_ms, 2),
    )

    _jobs[job_id]["status"] = "DONE"
    _jobs[job_id]["result"] = response.model_dump()

    # Best-effort MinIO persistence
    _store_result_minio(job_id, response)

    logger.info(
        "Sync inference done — job=%s instances=%d time=%.1fms",
        job_id,
        len(results),
        elapsed_ms,
    )
    return response


@app.post("/infer/async", response_model=JobStatusResponse, status_code=202)
async def infer_async(
    request: InferRequest,
    background_tasks: BackgroundTasks,
) -> JobStatusResponse:
    """
    Asynchronous inference — returns job ID immediately; poll /infer/{job_id} for status.
    """
    if not request.instance_uids:
        raise HTTPException(status_code=400, detail="instance_uids must not be empty")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "PENDING"}

    background_tasks.add_task(_run_inference_task, job_id, request)

    return JobStatusResponse(job_id=job_id, status="PENDING")


@app.get("/infer/{job_id}", response_model=JobStatusResponse)
def get_infer_status(job_id: str) -> JobStatusResponse:
    """Poll the status of an async inference job."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    result_url = None
    if job["status"] == "DONE":
        # Return a URL the caller can use to retrieve the full result
        result_url = f"/infer/{job_id}/result"

    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        result_url=result_url,
        error=job.get("error"),
    )


@app.get("/infer/{job_id}/result")
def get_infer_result(job_id: str) -> dict[str, Any]:
    """Return the full inference result payload for a completed job."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job["status"] != "DONE":
        raise HTTPException(status_code=409, detail=f"Job {job_id} is not done yet (status={job['status']})")
    return job["result"]
