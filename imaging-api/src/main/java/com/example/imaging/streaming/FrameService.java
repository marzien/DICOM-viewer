package com.example.imaging.streaming;

import org.dcm4che3.data.Attributes;
import org.dcm4che3.data.Tag;
import org.dcm4che3.data.UID;
import org.dcm4che3.imageio.codec.TransferSyntaxType;
import org.dcm4che3.io.DicomInputStream;
import org.dcm4che3.util.SafeClose;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.awt.image.DataBufferShort;
import java.awt.image.DataBufferUShort;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;

/**
 * Fetches a raw DICOM frame from Orthanc, applies window/level (linear rescale),
 * and returns a JPEG-encoded byte array.
 *
 * <p>Window/Level formula (standard linear):
 * <pre>
 *   if (pixel ≤ windowCenter - 0.5 - (windowWidth-1)/2)  → 0
 *   if (pixel >  windowCenter - 0.5 + (windowWidth-1)/2)  → 255
 *   else → ((pixel - (windowCenter-0.5)) / (windowWidth-1) + 0.5) * 255
 * </pre>
 */
@Service
public class FrameService {

    private static final Logger log = LoggerFactory.getLogger(FrameService.class);

    // Default W/L for CT (soft-tissue window)
    private static final double DEFAULT_WINDOW_CENTER = 40.0;
    private static final double DEFAULT_WINDOW_WIDTH = 400.0;

    private static final int JPEG_QUALITY = 85;

    private final RestClient orthanc;

    public FrameService(@Qualifier("orthancRestClient") RestClient orthanc) {
        this.orthanc = orthanc;
    }

    /**
     * Returns a JPEG-encoded, window/levelled frame.
     *
     * @param instanceUID   DICOM SOP Instance UID
     * @param frameNumber   1-based frame index
     * @param windowCenter  window center (VOI LUT)
     * @param windowWidth   window width  (VOI LUT)
     */
    public byte[] getFrameJpeg(String instanceUID, int frameNumber,
                                double windowCenter, double windowWidth) throws IOException {
        byte[] dicomBytes = fetchRawFrame(instanceUID, frameNumber);
        return renderToJpeg(dicomBytes, windowCenter, windowWidth, 1.0);
    }

    /**
     * Returns a 1/4-resolution JPEG thumbnail of the frame.
     */
    public byte[] getThumbnail(String instanceUID, int frameNumber,
                                double windowCenter, double windowWidth) throws IOException {
        byte[] dicomBytes = fetchRawFrame(instanceUID, frameNumber);
        return renderToJpeg(dicomBytes, windowCenter, windowWidth, 0.25);
    }

    // ── private helpers ──────────────────────────────────────────────────────

    /**
     * Fetches raw DICOM bytes for a single frame from Orthanc REST API.
     * Path: /instances/{instanceUID}/frames/{frame-0based}/raw
     */
    private byte[] fetchRawFrame(String instanceUID, int frameNumber) {
        // Orthanc uses 0-based frame indices
        int orthancFrame = frameNumber - 1;
        String path = "/instances/" + instanceUID + "/frames/" + orthancFrame + "/raw";
        log.debug("Fetching raw frame: {}", path);

        return orthanc.get()
                .uri(path)
                .retrieve()
                .body(byte[].class);
    }

    /**
     * Parses DICOM bytes, extracts pixel data, applies W/L, renders as JPEG.
     * Falls back to a synthetic grey image if parsing fails (e.g. non-DICOM raw frame).
     */
    private byte[] renderToJpeg(byte[] dicomBytes, double windowCenter, double windowWidth,
                                 double scaleFactor) throws IOException {

        BufferedImage image;
        try {
            image = parseDicomToImage(dicomBytes, windowCenter, windowWidth);
        } catch (Exception e) {
            log.warn("Could not parse DICOM pixel data ({}), rendering placeholder", e.getMessage());
            image = syntheticGrey(512, 512);
        }

        if (scaleFactor < 1.0) {
            int w = Math.max(1, (int) (image.getWidth() * scaleFactor));
            int h = Math.max(1, (int) (image.getHeight() * scaleFactor));
            BufferedImage scaled = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_GRAY);
            Graphics2D g = scaled.createGraphics();
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,
                    RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            g.drawImage(image, 0, 0, w, h, null);
            g.dispose();
            image = scaled;
        }

        return encodeJpeg(image);
    }

    private BufferedImage parseDicomToImage(byte[] bytes, double wc, double ww) throws IOException {
        try (DicomInputStream dis = new DicomInputStream(new ByteArrayInputStream(bytes))) {
            Attributes fmi = dis.readFileMetaInformation();
            Attributes dataset = dis.readDataset();

            int rows = dataset.getInt(Tag.Rows, 512);
            int cols = dataset.getInt(Tag.Columns, 512);
            int bitsAllocated = dataset.getInt(Tag.BitsAllocated, 16);
            int bitsStored = dataset.getInt(Tag.BitsStored, bitsAllocated);
            int pixelRepresentation = dataset.getInt(Tag.PixelRepresentation, 0); // 0=unsigned,1=signed
            double rescaleSlope = dataset.getDouble(Tag.RescaleSlope, 1.0);
            double rescaleIntercept = dataset.getDouble(Tag.RescaleIntercept, 0.0);

            byte[] pixelBytes = dataset.getBytes(Tag.PixelData);
            if (pixelBytes == null) {
                throw new IOException("No PixelData in DICOM dataset");
            }

            return applyWindowLevel(pixelBytes, rows, cols, bitsAllocated, pixelRepresentation,
                    rescaleSlope, rescaleIntercept, wc, ww);
        }
    }

    private BufferedImage applyWindowLevel(byte[] pixelBytes, int rows, int cols,
                                            int bitsAllocated, int pixelRepresentation,
                                            double slope, double intercept,
                                            double wc, double ww) {

        BufferedImage output = new BufferedImage(cols, rows, BufferedImage.TYPE_BYTE_GRAY);
        byte[] outPixels = ((java.awt.image.DataBufferByte) output.getRaster().getDataBuffer()).getData();

        double lower = wc - 0.5 - (ww - 1.0) / 2.0;
        double upper = wc - 0.5 + (ww - 1.0) / 2.0;
        int totalPixels = rows * cols;

        if (bitsAllocated <= 8) {
            // 8-bit: each pixel is one byte
            for (int i = 0; i < totalPixels && i < pixelBytes.length; i++) {
                int raw = pixelRepresentation == 1 ? pixelBytes[i] : (pixelBytes[i] & 0xFF);
                double hu = raw * slope + intercept;
                outPixels[i] = (byte) clampToLut(hu, lower, upper);
            }
        } else {
            // 16-bit: two bytes per pixel (little-endian)
            for (int i = 0; i < totalPixels; i++) {
                int byteIdx = i * 2;
                if (byteIdx + 1 >= pixelBytes.length) break;
                int low = pixelBytes[byteIdx] & 0xFF;
                int high = pixelBytes[byteIdx + 1] & 0xFF;
                int raw = low | (high << 8);
                if (pixelRepresentation == 1 && raw > 32767) raw -= 65536; // signed
                double hu = raw * slope + intercept;
                outPixels[i] = (byte) clampToLut(hu, lower, upper);
            }
        }

        return output;
    }

    /** Standard linear VOI LUT mapping to [0,255]. */
    private int clampToLut(double value, double lower, double upper) {
        if (value <= lower) return 0;
        if (value > upper) return 255;
        return (int) (((value - lower) / (upper - lower)) * 255.0);
    }

    private BufferedImage syntheticGrey(int w, int h) {
        BufferedImage img = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_GRAY);
        Graphics2D g = img.createGraphics();
        g.setColor(new Color(40, 40, 40));
        g.fillRect(0, 0, w, h);
        g.setColor(Color.LIGHT_GRAY);
        g.setFont(new Font("SansSerif", Font.PLAIN, 20));
        g.drawString("No pixel data", w / 2 - 60, h / 2);
        g.dispose();
        return img;
    }

    private byte[] encodeJpeg(BufferedImage image) throws IOException {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        // Convert to TYPE_INT_RGB if needed for JPEG writer
        BufferedImage rgb = new BufferedImage(image.getWidth(), image.getHeight(),
                BufferedImage.TYPE_INT_RGB);
        Graphics2D g = rgb.createGraphics();
        g.drawImage(image, 0, 0, null);
        g.dispose();
        ImageIO.write(rgb, "jpeg", baos);
        return baos.toByteArray();
    }
}
