package com.example.imaging.ai;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.Instant;
import java.util.UUID;

/**
 * JPA entity representing a single AI inference job.
 *
 * Lifecycle: PENDING → RUNNING → DONE | FAILED
 * The resultUrl points to a MinIO object containing the inference result JSON.
 */
@Entity
@Table(name = "ai_jobs")
@Getter
@Setter
@NoArgsConstructor
public class AiJob {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(columnDefinition = "uuid")
    private UUID id;

    @Column(name = "study_uid", nullable = false)
    private String studyUid;

    @Column(name = "series_uid", nullable = false)
    private String seriesUid;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private JobStatus status = JobStatus.PENDING;

    @Column(name = "result_url", length = 2048)
    private String resultUrl;

    @Column(name = "error_message", length = 1024)
    private String errorMessage;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private Instant createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private Instant updatedAt;

    public enum JobStatus {
        PENDING, RUNNING, DONE, FAILED
    }
}
