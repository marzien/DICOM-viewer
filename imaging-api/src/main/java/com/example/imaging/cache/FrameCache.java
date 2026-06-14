package com.example.imaging.cache;

import com.example.imaging.streaming.FrameService;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Component;

import java.io.IOException;

/**
 * Caffeine-backed cache wrapper for FrameService.
 *
 * Cache key: (instanceUID, frameNumber, windowCenter, windowWidth)
 * Max entries: 500 (configured in AppConfig / application.properties)
 * TTL: 10 minutes after write
 *
 * Kept as a separate @Component (not on FrameService directly) so that
 * Spring's AOP proxy can intercept @Cacheable calls correctly.
 */
@Component
public class FrameCache {

    private final FrameService frameService;

    public FrameCache(FrameService frameService) {
        this.frameService = frameService;
    }

    /**
     * Returns a JPEG-encoded, window/levelled frame, served from cache when available.
     *
     * @param instanceUID  DICOM SOP Instance UID
     * @param frameNumber  1-based frame index
     * @param windowCenter VOI LUT window centre
     * @param windowWidth  VOI LUT window width
     */
    @Cacheable(value = "frames",
               key = "#instanceUID + '-' + #frameNumber + '-' + #windowCenter + '-' + #windowWidth")
    public byte[] getFrame(String instanceUID, int frameNumber,
                           double windowCenter, double windowWidth) throws IOException {
        return frameService.getFrameJpeg(instanceUID, frameNumber, windowCenter, windowWidth);
    }

    /**
     * Returns a 1/4-resolution thumbnail JPEG, served from cache when available.
     */
    @Cacheable(value = "frames",
               key = "'thumb-' + #instanceUID + '-' + #frameNumber + '-' + #windowCenter + '-' + #windowWidth")
    public byte[] getThumbnail(String instanceUID, int frameNumber,
                               double windowCenter, double windowWidth) throws IOException {
        return frameService.getThumbnail(instanceUID, frameNumber, windowCenter, windowWidth);
    }
}
