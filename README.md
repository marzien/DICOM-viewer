# AGFA Imaging Demo — Zero-Footprint DICOM Viewer

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Browser (Port 4200)                            │
│                     Angular 17 + Cornerstone3D                         │
│          Worklist ──► Viewer ──► W/L drag, pan/zoom, AI overlay        │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ HTTP (WADO-RS / QIDO-RS / AI REST)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    imaging-api  (Spring Boot 3 / Java 21)               │
│                                                                         │
│  QidoController ──► proxy QIDO-RS ──► Orthanc                          │
│  WadoController ──► FrameService ──► Orthanc raw frame                 │
│                          │                                              │
│                     W/L rescale (dcm4che)  + JPEG encode               │
│                          │                                              │
│                    FrameCache (Caffeine)                                │
│                                                                         │
│  AiJobController ──► AiJobService (@Async) ──► ai-inference            │
│                           │                         │                  │
│                      Postgres (jobs)            MinIO (results)        │
└──────────┬──────────────────────────────────┬───────────────────────────┘
           │                                  │
           ▼                                  ▼
   ┌───────────────┐                 ┌──────────────────┐
   │    Orthanc    │                 │   ai-inference   │
   │  (DICOM SCP + │                 │ (FastAPI / Py)   │
   │  DICOMweb)    │                 │  pydicom + numpy │
   └───────┬───────┘                 └──────────────────┘
           │ stores DICOM objects
           ▼
   ┌───────────────┐
   │  PostgreSQL   │  (Orthanc DB + imaging-api job table)
   └───────────────┘

   ┌───────────────┐
   │    MinIO      │  (AI result JSON blobs)
   └───────────────┘
```

## Quick Start

```bash
cp .env.example .env
docker compose up --build
# In a separate terminal, load sample DICOM data:
bash scripts/load-tcia-sample.sh
```

Then open **http://localhost:4200** — the worklist loads automatically.

## Services & Ports

| Service       | Port  | Purpose                                    |
|---------------|-------|--------------------------------------------|
| viewer        | 4200  | Angular SPA (nginx)                        |
| imaging-api   | 8080  | Spring Boot REST (QIDO/WADO proxy + AI)    |
| ai-inference  | 8000  | FastAPI inference service                  |
| orthanc       | 8042  | DICOM SCP + DICOMweb (Orthanc REST)        |
| postgres      | 5432  | Orthanc metadata + job tracking            |
| minio         | 9000  | AI result object storage (S3-compatible)   |

## 2-Minute Pitch

This demo showcases a full-stack, zero-footprint DICOM viewer architected to the same patterns used in production enterprise imaging platforms. The **Angular + Cornerstone3D** front end delivers a true zero-footprint experience — no plugin, no download — while the **Spring Boot imaging-api** enforces server-side window/level and acts as a conformant DICOMweb façade over Orthanc. A **FastAPI AI service** demonstrates the async job pattern used for real AI inference pipelines: POST a job, poll for status, receive a structured overlay result. All components run as containers orchestrated by Docker Compose, mirroring a Kubernetes-ready microservice topology. The design decisions document explains every architectural trade-off made, which patterns were consciously deferred (auth/RBAC, IHE ATNA, HA, MDR regulatory scope), and how the system would scale to a real PACS integration — demonstrating the depth of enterprise imaging knowledge behind each choice.

## Development

```bash
# imaging-api
cd imaging-api && mvn spring-boot:run

# ai-inference
cd ai-inference && uvicorn app.main:app --reload --port 8000

# viewer
cd viewer && npm install && ng serve
```
