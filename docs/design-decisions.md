# Design Decisions

## 1. Server-Side Window/Level vs. WASM Client-Side Decode

**Decision:** Server-side window/level with JPEG output from imaging-api.

**Options considered:**
- *Client-side WASM decode* — ship raw DICOM frames to the browser; Cornerstone3D + dicom-image-loader decode pixel data in a Web Worker using WASM (dcmjs, cornerstoneWADOImageLoader). Window/level is applied in the GPU shader via a LUT texture. This is the modern "zero-footprint" gold standard for interactive W/L.
- *Server-side W/L* — imaging-api reads raw pixels, applies the linear rescale (`output = (pixel * slope + intercept - windowCenter + windowWidth/2) / windowWidth`), JPEG-encodes, returns. The browser receives a standard image.

**Choice:** Server-side W/L for this demo, with the architecture prepared to switch.

**Why:** The demo must run without a real DICOM dataset that includes proper pixel data headers, and server-side W/L eliminates the "blank canvas" failure mode when WASM decoders encounter unexpected transfer syntaxes. In a production system at scale the trade-off reverses: server-side W/L burns CPU and bandwidth on every W/L drag event, while WASM decode sends each frame once and applies W/L at 60fps on the GPU. The `WadoController` already accepts `windowCenter` and `windowWidth` query params so the client can drive W/L changes — the cache key includes those values, so repeated requests at the same W/L hit memory instantly.

---

## 2. Streaming Strategy — Thumbnail → Progressive → Prefetch → Cache

**Decision:** Four-tier progressive delivery pattern.

**Tiers:**
1. **Thumbnail** — `FrameService.getThumbnail()` returns a 1/4-resolution JPEG immediately. The viewer renders this while full frames load.
2. **Progressive** — Full-resolution frames are fetched on demand as the user scrolls. The Cornerstone3D `StackViewport` drives this naturally via its image loader.
3. **Prefetch** — After the current frame renders, the viewer prefetches adjacent frames (current ± 2) by issuing background `GET /wado/rs/.../frames/{n}` requests. Cornerstone's `StackScrollMouseWheelTool` triggers `cornerstoneStreamingImageVolume` for volume use cases.
4. **Cache** — `FrameCache` (Caffeine, max 500 entries, expire-after-write 10 min) stores rendered JPEG bytes keyed by `(instanceUID, frame, wc, ww)`. A repeated scroll to the same frame is a memory hit with sub-millisecond latency.

**Why this order:** Thumbnail satisfies the "time to first meaningful paint" requirement. Progressive avoids loading the full series before the user sees anything. Prefetch eliminates stutter during sequential scroll. Cache avoids redundant work when the user re-examines a previously viewed frame.

---

## 3. DICOMweb Conformance

**Decision:** imaging-api acts as a conformant DICOMweb proxy façade over Orthanc.

**Options:**
- *Expose Orthanc DICOMweb directly* — simplest, but exposes Orthanc credentials and bypasses caching and W/L.
- *Implement DICOMweb natively* — parse DICOM files from storage ourselves without Orthanc.
- *Proxy with transformation* — imaging-api passes QIDO-RS through verbatim and transforms WADO-RS frame responses (W/L, JPEG encode, cache).

**Choice:** Proxy with transformation.

**Why:** QIDO-RS JSON responses are passed through unchanged — Orthanc's DICOMweb plugin produces conformant DICOM JSON (PS3.18). WADO-RS frame retrieval is intercepted so imaging-api can own the rendering pipeline (W/L, cache, thumbnail). This preserves the ability to swap Orthanc for a different PACS (e.g., DCM4CHEE) by changing `ORTHANC_BASE_URL` and adjusting the frame-fetch path in `FrameService`.

---

## 4. Async AI Job Pattern

**Decision:** POST-to-submit / GET-to-poll with Postgres-backed state and MinIO result storage.

**Options:**
- *Synchronous inference* — block the HTTP request until inference completes. Simple but breaks on long-running models (CT segmentation: 30–120 s).
- *WebSocket push* — server pushes status updates to the viewer. Better UX but adds connection management complexity.
- *POST/poll* — submit job, get an ID, poll for status. Ubiquitous in cloud AI APIs (Azure AI, AWS Rekognition, Google Healthcare AI).

**Choice:** POST/poll with 2-second client poll interval.

**Why:** POST/poll is stateless on the server side (each poll is independent), survives imaging-api restarts (job state is in Postgres), and is the de facto standard for enterprise AI inference pipelines. The viewer polls every 2 seconds — acceptable for a demo. In production, replace polling with Server-Sent Events or a WebSocket channel for sub-second latency. Result payloads (JSON mask objects) are stored in MinIO, not in the Postgres row, to avoid row bloat when results grow (e.g., full segmentation masks).

---

## 5. Storage Split — Orthanc Volume vs. MinIO

**Decision:** DICOM pixel data in Orthanc's managed volume; AI results in MinIO.

**Why:** Orthanc owns the DICOM object lifecycle (C-STORE, WADO-RS, retention policies). Mixing AI result blobs into Orthanc's storage would couple AI job management to the DICOM server's retention and access-control rules. MinIO provides an S3-compatible API that is standard for unstructured blob storage, supports pre-signed URLs for direct browser download, and is independently scalable.

---

## What Was Deliberately NOT Built

### Authentication / RBAC
No user authentication, role-based access control, or session management. In a production deployment this would be handled by an external IdP (Keycloak, Azure AD) via OIDC, with JWT bearer tokens validated in imaging-api and role claims mapped to study-level permissions. Orthanc supports HTTP basic auth and LDAP integration. Not built here to keep the demo focus on imaging-specific concerns.

### Audit / ATNA
No IHE ATNA (Audit Trail and Node Authentication) integration. Production clinical systems must emit audit events for every DICOM access (DICOM PS3.15 Annex A). This requires a syslog-compatible audit repository and TLS mutual-auth node authentication. Out of scope for a portfolio demo.

### High Availability
Single-instance of every service. Production would require: Orthanc in clustered mode with shared storage (NFS or S3 backend), imaging-api behind a load balancer with sticky sessions or stateless JWT, Postgres in streaming-replication primary/replica topology, MinIO in distributed mode across 4+ nodes.

### Multi-Tenancy
All studies are visible to all users. Production multi-tenant deployments use study-level ownership in Orthanc (via `OrganisationRoot` labels or a separate metadata layer), combined with RBAC to enforce tenant isolation.

### IHE Conformance (XDS, XCA, MHD)
No IHE profiles implemented. Relevant profiles for a real PACS integration would include: XDS.b (Cross-Enterprise Document Sharing), RAD-69 (WADO-RS Retrieve), RAD-55 (WADO Retrieve), XCA (Cross-Community Access). Conformance statements and integration statements are not provided.

### MDR / IEC 62304 Regulatory Scope
This is a portfolio demo, not a medical device. Production AI inference results displayed on a clinical viewer require: IEC 62304 software lifecycle documentation, risk management per ISO 14971, clinical validation studies, and MDR (EU) or 510(k)/De Novo (US) regulatory clearance for the AI algorithms. The AI service here produces simulated results with no clinical validity.

---

## Scaling to a Real PACS Integration

1. **Replace Orthanc with DCM4CHEE or Nuance PowerShare** — imaging-api's `ORTHANC_BASE_URL` is the only touch point. Adjust the frame-fetch URL pattern in `FrameService` to match the target PACS DICOMweb base path.
2. **Add a message queue** — replace `@Async` with a Kafka or RabbitMQ consumer in `AiJobService` to handle burst AI job submission without exhausting the thread pool.
3. **GPU inference** — replace the simulated numpy mask in ai-inference with an ONNX Runtime GPU session loading a real segmentation model. The API contract (POST/poll, JSON mask response) does not change.
4. **Volume rendering** — Cornerstone3D supports `VolumeViewport` for MPR (multi-planar reconstruction). Switch the viewer component from `StackViewport` to `VolumeViewport` and use `cornerstoneStreamingImageVolume` to stream the full series.
5. **Pre-signed MinIO URLs** — Instead of returning AI result JSON through imaging-api, generate a pre-signed MinIO URL and return it to the viewer for direct download, eliminating imaging-api from the result-fetch path.
