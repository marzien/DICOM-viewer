import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

/**
 * DICOMweb service — wraps QIDO-RS and WADO-RS calls to imaging-api.
 *
 * In production the base URL is proxied by nginx so no CORS issues arise.
 * For local dev (ng serve), a proxy.conf.json can forward /wado/ to imaging-api:8080.
 */
@Injectable({ providedIn: 'root' })
export class DicomWebService {
  private readonly qidoBase = '/wado/rs';

  constructor(private http: HttpClient) {}

  /** QIDO-RS: search all studies */
  searchStudies(filters: Record<string, string> = {}): Observable<DicomStudy[]> {
    let params = new HttpParams();
    Object.entries(filters).forEach(([k, v]) => { params = params.set(k, v); });
    return this.http.get<DicomStudy[]>(`${this.qidoBase}/studies`, { params });
  }

  /** QIDO-RS: list series in a study */
  searchSeries(studyUID: string): Observable<DicomSeries[]> {
    return this.http.get<DicomSeries[]>(`${this.qidoBase}/studies/${studyUID}/series`);
  }

  /** QIDO-RS: list instances in a series */
  searchInstances(studyUID: string, seriesUID: string): Observable<DicomInstance[]> {
    return this.http.get<DicomInstance[]>(
      `${this.qidoBase}/studies/${studyUID}/series/${seriesUID}/instances`
    );
  }

  /**
   * Build the WADO-RS frame URL (consumed by <img src="..."> or fetch).
   * The imaging-api applies server-side window/level and returns JPEG.
   */
  frameUrl(
    studyUID: string,
    seriesUID: string,
    instanceUID: string,
    frame: number,
    windowCenter?: number,
    windowWidth?: number
  ): string {
    let url = `${this.qidoBase}/studies/${studyUID}/series/${seriesUID}/instances/${instanceUID}/frames/${frame}`;
    const params: string[] = [];
    if (windowCenter !== undefined) params.push(`windowCenter=${windowCenter}`);
    if (windowWidth !== undefined) params.push(`windowWidth=${windowWidth}`);
    if (params.length) url += '?' + params.join('&');
    return url;
  }

  /** Thumbnail URL (1/4 resolution) for fast initial display */
  thumbnailUrl(
    studyUID: string,
    seriesUID: string,
    instanceUID: string,
    frame: number
  ): string {
    return `${this.qidoBase}/studies/${studyUID}/series/${seriesUID}/instances/${instanceUID}/frames/${frame}/thumbnail`;
  }
}

// ── DICOM JSON attribute helpers ─────────────────────────────────────────────

/** Extract a string value from a DICOM JSON attribute (Value[0]) */
export function dicomStr(attr: DicomAttr | undefined): string {
  if (!attr || !attr.Value || !attr.Value.length) return '';
  const v = attr.Value[0];
  if (typeof v === 'string') return v;
  if (typeof v === 'object' && v !== null && 'Alphabetic' in v) {
    return (v as { Alphabetic: string }).Alphabetic;
  }
  return String(v);
}

export function dicomNum(attr: DicomAttr | undefined): number | null {
  if (!attr || !attr.Value || !attr.Value.length) return null;
  return Number(attr.Value[0]);
}

// ── DICOM JSON types (PS3.18 §F.2) ──────────────────────────────────────────

export interface DicomAttr {
  vr: string;
  Value?: unknown[];
}

export interface DicomStudy {
  '0020000D': DicomAttr; // StudyInstanceUID
  '00100010': DicomAttr; // PatientName
  '00100020': DicomAttr; // PatientID
  '00080020': DicomAttr; // StudyDate
  '00080030': DicomAttr; // StudyTime
  '00081030': DicomAttr; // StudyDescription
  '00080061': DicomAttr; // ModalitiesInStudy
  '00200010': DicomAttr; // StudyID
  [tag: string]: DicomAttr;
}

export interface DicomSeries {
  '0020000E': DicomAttr; // SeriesInstanceUID
  '00080060': DicomAttr; // Modality
  '00200011': DicomAttr; // SeriesNumber
  '0008103E': DicomAttr; // SeriesDescription
  '00201209': DicomAttr; // NumberOfSeriesRelatedInstances
  [tag: string]: DicomAttr;
}

export interface DicomInstance {
  '00080018': DicomAttr; // SOPInstanceUID
  '00200013': DicomAttr; // InstanceNumber
  [tag: string]: DicomAttr;
}
