import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, interval, switchMap, takeWhile, map } from 'rxjs';

export interface AiJobRequest {
  studyUid: string;
  seriesUid: string;
  instanceUids: string[];
}

export interface AiJobStatus {
  id: string;
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED';
  studyUid: string;
  seriesUid: string;
  resultUrl: string | null;
  errorMessage: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface MaskResult {
  instance_uid: string;
  rows: number;
  cols: number;
  mask: {
    cx: number;
    cy: number;
    r: number;
    label: string;
    confidence: number;
    type: string;
  };
}

export interface AiInferResult {
  job_id: string;
  study_uid: string;
  series_uid: string;
  results: MaskResult[];
  processing_time_ms: number;
}

@Injectable({ providedIn: 'root' })
export class AiService {
  private readonly base = '/ai';

  constructor(private http: HttpClient) {}

  /** Submit a new AI inference job. Returns the job ID and initial status. */
  submitJob(request: AiJobRequest): Observable<{ id: string; status: string }> {
    return this.http.post<{ id: string; status: string }>(`${this.base}/jobs`, request);
  }

  /** Poll a job's status once. */
  pollJob(jobId: string): Observable<AiJobStatus> {
    return this.http.get<AiJobStatus>(`${this.base}/jobs/${jobId}`);
  }

  /**
   * Poll a job every 2 seconds until it reaches DONE or FAILED.
   * Emits each status update so the caller can update the UI incrementally.
   */
  pollUntilDone(jobId: string): Observable<AiJobStatus> {
    return interval(2000).pipe(
      switchMap(() => this.pollJob(jobId)),
      takeWhile(status => status.status === 'PENDING' || status.status === 'RUNNING', true)
    );
  }

  /** Fetch inference result JSON from imaging-api (which proxies MinIO). */
  getResult(resultUrl: string): Observable<AiInferResult> {
    return this.http.get<AiInferResult>(resultUrl);
  }
}
