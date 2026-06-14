# Architecture

## Component Overview

### viewer (Angular 17 + Cornerstone3D)
The single-page application served by nginx on port 4200. It contains two primary views:
- **Worklist** — queries the imaging-api QIDO-RS proxy, renders a study table, and navigates to the viewer on row click.
- **Viewer** — initialises a Cornerstone3D `RenderingEngine` with a `StackViewport`, loads frames via WADO-RS URLs, and exposes mouse bindings for window/level, pan, and zoom. An "AI Analyse" button triggers async inference and draws a circular overlay when the job completes.

nginx proxies `/wado/` and `/ai/` to `imaging-api` so the SPA operates entirely on its own origin (no CORS from the browser's perspective in production).

### imaging-api (Spring Boot 3 / Java 21)
The central backend. Responsibilities:
1. **DICOMweb proxy** — QIDO-RS and WADO-RS endpoints forward requests to Orthanc. WADO frame requests pass through `FrameService`, which fetches the raw DICOM pixel data from Orthanc, applies server-side window/level using dcm4che, JPEG-encodes the result, and returns it.
2. **Frame cache** — `FrameCache` wraps `FrameService` with a Caffeine in-process cache keyed by `(instanceUID, frame, windowCenter, windowWidth)`. Reduces redundant Orthanc calls for repeated pan/scroll.
3. **AI job orchestration** — `AiJobController` accepts job submissions and status polls. `AiJobService` dispatches to the ai-inference service asynchronously, stores the result JSON in MinIO, and updates the job entity in Postgres.

### ai-inference (FastAPI / Python)
Lightweight inference sidecar. Accepts a list of instance UIDs, fetches DICOM metadata (from the request payload), runs a simulated ROI detection (numpy circular mask centred on the image), and persists the result JSON to MinIO. Designed to be replaced by a real ONNX or TorchScript model without changing the API contract.

### Orthanc
Open-source DICOM server providing:
- DICOM SCP (C-STORE, C-FIND, C-MOVE)
- Native DICOMweb (QIDO-RS, WADO-RS, STOW-RS) via the DICOMweb plugin
- REST API for frame-level pixel data retrieval

Orthanc stores metadata in PostgreSQL (via the orthanc-postgresql plugin) and pixel data on a mounted volume.

### PostgreSQL
Shared database:
- Orthanc metadata tables (managed by Orthanc PostgreSQL plugin)
- `ai_jobs` table (managed by imaging-api JPA/Hibernate)

### MinIO
S3-compatible object store used exclusively for AI inference result payloads. Decouples result storage from the imaging-api process lifetime and allows the viewer to fetch result JSON directly from a pre-signed URL in future iterations.

## Data Flow — Study Open

```
Browser                   imaging-api              Orthanc          Postgres
   │                           │                      │                │
   │  GET /wado/rs/studies     │                      │                │
   │──────────────────────────►│                      │                │
   │                           │  GET /dicom-web/studies               │
   │                           │─────────────────────►│                │
   │                           │  200 JSON            │                │
   │                           │◄─────────────────────│                │
   │  200 JSON (studies)       │                      │                │
   │◄──────────────────────────│                      │                │
   │                           │                      │                │
   │  GET /wado/rs/studies/{uid}/series/{s}/instances/{i}/frames/1     │
   │──────────────────────────►│                      │                │
   │                           │  GET /instances/{i}/frames/1/raw      │
   │                           │─────────────────────►│                │
   │                           │  200 raw pixels      │                │
   │                           │◄─────────────────────│                │
   │                           │ [W/L + JPEG encode]  │                │
   │                           │ [Caffeine cache hit  │                │
   │                           │  on repeat]          │                │
   │  200 JPEG                 │                      │                │
   │◄──────────────────────────│                      │                │
```

## Data Flow — AI Job

```
Browser          imaging-api        ai-inference          MinIO        Postgres
   │                  │                   │                 │              │
   │  POST /ai/jobs   │                   │                 │              │
   │─────────────────►│                   │                 │              │
   │                  │ INSERT job(PENDING)│                │              │
   │                  │──────────────────────────────────────────────────►│
   │  202 {id}        │                   │                 │              │
   │◄─────────────────│                   │                 │              │
   │                  │ @Async ─────────► │                 │              │
   │                  │  POST /infer      │                 │              │
   │                  │                   │ compute masks   │              │
   │                  │                   │─────────────────►              │
   │                  │                   │ PUT result.json │              │
   │                  │                   │◄────────────────│              │
   │                  │  200 {result_url} │                 │              │
   │                  │◄──────────────────│                 │              │
   │                  │ UPDATE job(DONE)  │                 │              │
   │                  │──────────────────────────────────────────────────►│
   │                  │                   │                 │              │
   │  GET /ai/jobs/id │                   │                 │              │
   │─────────────────►│                   │                 │              │
   │  200 {DONE, url} │                   │                 │              │
   │◄─────────────────│                   │                 │              │
```
