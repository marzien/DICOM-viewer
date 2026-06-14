package com.example.imaging.ai;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Async service that orchestrates AI inference for a given study/series.
 *
 * Flow:
 *   1. Update job status → RUNNING
 *   2. POST to ai-inference /infer with instance UIDs
 *   3. ai-inference processes synchronously (demo) and returns result JSON
 *   4. Store result JSON in MinIO
 *   5. Update job status → DONE with resultUrl
 *
 * In production step 2-3 would be a poll loop against the inference service's job API.
 */
@Service
public class AiJobService {

    private static final Logger log = LoggerFactory.getLogger(AiJobService.class);

    private final AiJobRepository jobRepository;
    private final RestClient aiRestClient;
    private final MinioClient minioClient;
    private final ObjectMapper objectMapper;

    @Value("${minio.bucket}")
    private String minioBucket;

    public AiJobService(AiJobRepository jobRepository,
                        @Qualifier("aiRestClient") RestClient aiRestClient,
                        MinioClient minioClient,
                        ObjectMapper objectMapper) {
        this.jobRepository = jobRepository;
        this.aiRestClient = aiRestClient;
        this.minioClient = minioClient;
        this.objectMapper = objectMapper;
    }

    /**
     * Runs in a separate thread (asyncExecutor pool).
     * Submits inference request, stores result, updates job entity.
     */
    @Async("asyncExecutor")
    public void runInference(UUID jobId, String studyUid, String seriesUid,
                             List<String> instanceUids) {
        log.info("Starting AI inference for job {} study={} series={}", jobId, studyUid, seriesUid);

        AiJob job = jobRepository.findById(jobId)
                .orElseThrow(() -> new IllegalStateException("Job not found: " + jobId));
        job.setStatus(AiJob.JobStatus.RUNNING);
        jobRepository.save(job);

        try {
            // Call ai-inference /infer endpoint
            Map<String, Object> request = Map.of(
                    "study_uid", studyUid,
                    "series_uid", seriesUid,
                    "instance_uids", instanceUids
            );

            String responseJson = aiRestClient.post()
                    .uri("/infer")
                    .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                    .body(request)
                    .retrieve()
                    .body(String.class);

            log.debug("AI inference response for {}: {}", jobId, responseJson);

            // Store result JSON in MinIO
            String objectName = "results/" + jobId + ".json";
            byte[] resultBytes = responseJson.getBytes(StandardCharsets.UTF_8);

            ensureBucketExists();

            minioClient.putObject(
                    PutObjectArgs.builder()
                            .bucket(minioBucket)
                            .object(objectName)
                            .stream(new ByteArrayInputStream(resultBytes), resultBytes.length, -1)
                            .contentType("application/json")
                            .build()
            );

            String resultUrl = "/ai/results/" + jobId;
            job.setStatus(AiJob.JobStatus.DONE);
            job.setResultUrl(resultUrl);
            jobRepository.save(job);

            log.info("AI inference completed for job {} → {}", jobId, resultUrl);

        } catch (Exception e) {
            log.error("AI inference failed for job {}: {}", jobId, e.getMessage(), e);
            job.setStatus(AiJob.JobStatus.FAILED);
            job.setErrorMessage(e.getMessage());
            jobRepository.save(job);
        }
    }

    private void ensureBucketExists() {
        try {
            boolean exists = minioClient.bucketExists(
                    io.minio.BucketExistsArgs.builder().bucket(minioBucket).build());
            if (!exists) {
                minioClient.makeBucket(
                        io.minio.MakeBucketArgs.builder().bucket(minioBucket).build());
                log.info("Created MinIO bucket: {}", minioBucket);
            }
        } catch (Exception e) {
            log.warn("Could not verify/create MinIO bucket: {}", e.getMessage());
        }
    }
}
