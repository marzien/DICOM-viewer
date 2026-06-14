package com.example.imaging.dicomweb;

import com.example.imaging.cache.FrameCache;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * WADO-RS frame endpoint — serves JPEG-encoded, server-side window/levelled frames.
 *
 * GET /wado/rs/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}/frames/{frame}
 *
 * Optional query params:
 *   windowCenter  (default 40)
 *   windowWidth   (default 400)
 *
 * GET /wado/rs/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}/frames/{frame}/thumbnail
 *   Returns a 1/4-resolution preview for rapid initial display.
 */
@RestController
@RequestMapping("/wado/rs")
public class WadoController {

    private static final Logger log = LoggerFactory.getLogger(WadoController.class);

    private static final double DEFAULT_WC = 40.0;
    private static final double DEFAULT_WW = 400.0;

    private final FrameCache frameCache;

    public WadoController(FrameCache frameCache) {
        this.frameCache = frameCache;
    }

    @GetMapping("/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}/frames/{frame}")
    public ResponseEntity<byte[]> getFrame(
            @PathVariable String studyUID,
            @PathVariable String seriesUID,
            @PathVariable String instanceUID,
            @PathVariable int frame,
            @RequestParam(required = false) Double windowCenter,
            @RequestParam(required = false) Double windowWidth) {

        double wc = windowCenter != null ? windowCenter : DEFAULT_WC;
        double ww = windowWidth != null ? windowWidth : DEFAULT_WW;

        log.debug("WADO frame {}/{} wc={} ww={}", instanceUID, frame, wc, ww);

        try {
            byte[] jpeg = frameCache.getFrame(instanceUID, frame, wc, ww);
            return ResponseEntity.ok()
                    .contentType(MediaType.IMAGE_JPEG)
                    .body(jpeg);
        } catch (Exception e) {
            log.error("Failed to render frame {}/{}: {}", instanceUID, frame, e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY).build();
        }
    }

    @GetMapping("/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}/frames/{frame}/thumbnail")
    public ResponseEntity<byte[]> getThumbnail(
            @PathVariable String studyUID,
            @PathVariable String seriesUID,
            @PathVariable String instanceUID,
            @PathVariable int frame,
            @RequestParam(required = false) Double windowCenter,
            @RequestParam(required = false) Double windowWidth) {

        double wc = windowCenter != null ? windowCenter : DEFAULT_WC;
        double ww = windowWidth != null ? windowWidth : DEFAULT_WW;

        log.debug("WADO thumbnail {}/{}", instanceUID, frame);

        try {
            byte[] jpeg = frameCache.getThumbnail(instanceUID, frame, wc, ww);
            return ResponseEntity.ok()
                    .contentType(MediaType.IMAGE_JPEG)
                    .body(jpeg);
        } catch (Exception e) {
            log.error("Failed to render thumbnail {}/{}: {}", instanceUID, frame, e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY).build();
        }
    }
}
