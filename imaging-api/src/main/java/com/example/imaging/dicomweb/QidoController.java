package com.example.imaging.dicomweb;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * QIDO-RS proxy — forwards study and series search requests to Orthanc's DICOMweb plugin.
 *
 * Supported endpoints (DICOMweb PS3.18):
 *   GET /wado/rs/studies                        — search studies
 *   GET /wado/rs/studies/{studyUID}/series      — search series within a study
 */
@RestController
@RequestMapping("/wado/rs")
public class QidoController {

    private static final Logger log = LoggerFactory.getLogger(QidoController.class);

    private static final String DICOM_JSON = "application/dicom+json";
    private static final String ORTHANC_DICOMWEB_ROOT = "/dicom-web";

    private final RestClient orthanc;

    public QidoController(@Qualifier("orthancRestClient") RestClient orthanc) {
        this.orthanc = orthanc;
    }

    /**
     * QIDO-RS: Search Studies
     * Forwards all query parameters (PatientName, StudyDate, Modality, etc.) to Orthanc.
     */
    @GetMapping("/studies")
    public ResponseEntity<String> searchStudies(
            @RequestParam MultiValueMap<String, String> queryParams) {

        String orthancPath = buildQueryPath(ORTHANC_DICOMWEB_ROOT + "/studies", queryParams);
        log.debug("QIDO searchStudies → {}", orthancPath);

        String body = orthanc.get()
                .uri(orthancPath)
                .accept(MediaType.parseMediaType(DICOM_JSON))
                .retrieve()
                .body(String.class);

        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(DICOM_JSON))
                .body(body);
    }

    /**
     * QIDO-RS: Search Series
     * Returns all series belonging to the given study UID.
     */
    @GetMapping("/studies/{studyUID}/series")
    public ResponseEntity<String> searchSeries(
            @PathVariable String studyUID,
            @RequestParam MultiValueMap<String, String> queryParams) {

        String path = ORTHANC_DICOMWEB_ROOT + "/studies/" + studyUID + "/series";
        String orthancPath = buildQueryPath(path, queryParams);
        log.debug("QIDO searchSeries → {}", orthancPath);

        String body = orthanc.get()
                .uri(orthancPath)
                .accept(MediaType.parseMediaType(DICOM_JSON))
                .retrieve()
                .body(String.class);

        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(DICOM_JSON))
                .body(body);
    }

    /**
     * QIDO-RS: Search Instances within a series.
     */
    @GetMapping("/studies/{studyUID}/series/{seriesUID}/instances")
    public ResponseEntity<String> searchInstances(
            @PathVariable String studyUID,
            @PathVariable String seriesUID,
            @RequestParam MultiValueMap<String, String> queryParams) {

        String path = ORTHANC_DICOMWEB_ROOT + "/studies/" + studyUID
                + "/series/" + seriesUID + "/instances";
        String orthancPath = buildQueryPath(path, queryParams);
        log.debug("QIDO searchInstances → {}", orthancPath);

        String body = orthanc.get()
                .uri(orthancPath)
                .accept(MediaType.parseMediaType(DICOM_JSON))
                .retrieve()
                .body(String.class);

        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(DICOM_JSON))
                .body(body);
    }

    // ── helpers ───────────────────────────────────────────────────────────────

    private String buildQueryPath(String basePath, MultiValueMap<String, String> params) {
        if (params == null || params.isEmpty()) {
            return basePath;
        }
        return UriComponentsBuilder.fromPath(basePath)
                .queryParams(params)
                .build()
                .toUriString();
    }
}
