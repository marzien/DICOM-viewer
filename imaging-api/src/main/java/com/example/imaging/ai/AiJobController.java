package com.example.imaging.ai;

import io.minio.GetObjectArgs;
import io.minio.MinioClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * REST controller for AI inference job management.
 *
 * POST /ai/jobs       — submit a new inference job
 * GET  /ai/jobs/{id} — poll job status
 * GET  /ai/results/{id} — fetch result JSON from MinIO
 */
@RestController
@RequestMapping("/ai")
public class AiJobController {

    private final AiJobRepository jobRepository;
    private final AiJobService aiJobService;
    private final MinioClient minioClient;

    @Value("${minio.bucket}")
    private String minioBucket;

    public AiJobController(AiJobRepository jobRepository,
                           AiJobService aiJobService,
                           MinioClient minioClient) {
        this.jobRepository = jobRepository;
        this.aiJobService = aiJobService;
        this.minioClient = minioClient;
    }

    /**
     * Submit a new AI inference job.
     *
     * Request body:
     * {
     *   "studyUid": "...",
     *   "seriesUid": "...",
     *   "instanceUids": ["uid1", "uid2", ...]
     * }
     */
    @PostMapping("/jobs")
    public ResponseEntity<Map<String, Object>> submitJob(@RequestBody JobRequest request) {
        AiJob job = new AiJob();
        job.setStudyUid(request.studyUid());
        job.setSeriesUid(request.seriesUid());
        job.setStatus(AiJob.JobStatus.PENDING);
        AiJob saved = jobRepository.save(job);

        // Fire and forget — runs on asyncExecutor thread pool
        aiJobService.runInference(saved.getId(), request.studyUid(), request.seriesUid(),
                request.instanceUids());

        return ResponseEntity.accepted().body(Map.of(
                "id", saved.getId().toString(),
                "status", saved.getStatus().name()
        ));
    }

    /**
     * Poll job status.
     */
    @GetMapping("/jobs/{id}")
    public ResponseEntity<Map<String, Object>> getJob(@PathVariable UUID id) {
        return jobRepository.findById(id)
                .map(job -> {
                    Map<String, Object> body = new java.util.LinkedHashMap<>();
                    body.put("id", job.getId().toString());
                    body.put("status", job.getStatus().name());
                    body.put("studyUid", job.getStudyUid());
                    body.put("seriesUid", job.getSeriesUid());
                    body.put("resultUrl", job.getResultUrl());
                    body.put("errorMessage", job.getErrorMessage());
                    body.put("createdAt", job.getCreatedAt() != null ? job.getCreatedAt().toString() : null);
                    body.put("updatedAt", job.getUpdatedAt() != null ? job.getUpdatedAt().toString() : null);
                    return ResponseEntity.ok(body);
                })
                .orElse(ResponseEntity.notFound().<Map<String, Object>>build());
    }

    /**
     * Fetch AI result JSON from MinIO by job ID.
     */
    @GetMapping("/results/{id}")
    public ResponseEntity<String> getResult(@PathVariable UUID id) {
        String objectName = "results/" + id + ".json";
        try (InputStream stream = minioClient.getObject(
                GetObjectArgs.builder()
                        .bucket(minioBucket)
                        .object(objectName)
                        .build())) {
            String json = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
            return ResponseEntity.ok()
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(json);
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body("{\"error\": \"Result not found\"}");
        }
    }

    // ── DTOs ─────────────────────────────────────────────────────────────────

    public record JobRequest(String studyUid, String seriesUid, List<String> instanceUids) {}
}
