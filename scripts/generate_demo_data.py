#!/usr/bin/env python3
"""
generate_demo_data.py

Generates synthetic but visually realistic DICOM series and uploads them
to a local Orthanc instance. No real patient data — all synthetic.

Series generated:
  1. CT Chest    — 60 axial slices, lung/mediastinum anatomy
  2. CT Abdomen  — 45 axial slices, liver/kidney/bowel anatomy
  3. MRI Brain   — 30 axial slices, cortex/ventricle/white-matter
  4. MRI Spine   — 20 sagittal slices, vertebrae/discs/cord
  5. PET-CT      — 40 slices, hot-spot lesion overlay

Run:
  pip install pydicom numpy requests pillow
  python3 scripts/generate_demo_data.py
"""

import io
import math
import os
import random
import struct
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta

try:
    import numpy as np
except ImportError:
    sys.exit("Missing dependency: pip install numpy")

try:
    import pydicom
    from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
    from pydicom.sequence import Sequence
    from pydicom.uid import (
        ExplicitVRLittleEndian,
        generate_uid,
        CTImageStorage,
        MRImageStorage,
    )
    NM_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.20"
except ImportError:
    sys.exit("Missing dependency: pip install pydicom")

ORTHANC_URL = os.environ.get("ORTHANC_URL", "http://localhost:8042")
ORTHANC_USER = os.environ.get("ORTHANC_USER", "admin")
ORTHANC_PASS = os.environ.get("ORTHANC_PASS", "orthanc")

NOW = datetime.now()
STUDY_DATE = NOW.strftime("%Y%m%d")
STUDY_TIME = NOW.strftime("%H%M%S")

RNG = random.Random(42)
np.random.seed(42)


# ── DICOM construction helpers ────────────────────────────────────────────────

def make_uid() -> str:
    return generate_uid()


def ellipse(arr: np.ndarray, cx, cy, rx, ry, value, blur=0) -> np.ndarray:
    """Draw a filled ellipse on arr."""
    h, w = arr.shape
    Y, X = np.ogrid[:h, :w]
    mask = ((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2 <= 1
    arr[mask] = value
    return arr


def circle(arr, cx, cy, r, value):
    return ellipse(arr, cx, cy, r, r, value)


def noise(shape, sigma=30, rng=None):
    if rng is None:
        rng = np.random
    return (rng.randn(*shape) * sigma).astype(np.float32)


def smooth(arr, radius=3):
    """Simple box blur."""
    from numpy import ones
    k = ones((radius * 2 + 1, radius * 2 + 1)) / (radius * 2 + 1) ** 2
    # manual 2-D convolution via stride tricks for speed
    pad = radius
    p = np.pad(arr, pad, mode="edge").astype(np.float32)
    out = np.zeros_like(arr, dtype=np.float32)
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            out += p[dy:dy + arr.shape[0], dx:dx + arr.shape[1]]
    return out / (2 * radius + 1) ** 2


def build_ds(
    patient_name, patient_id, study_uid, series_uid,
    sop_class, instance_uid, series_desc, modality,
    slice_idx, n_slices,
    pixel_array,            # float32, raw HU or MR signal
    rescale_intercept=0,
    rescale_slope=1,
    window_center=40,
    window_width=400,
    pixel_spacing=(0.7, 0.7),
    slice_thickness=3.0,
    rows=512, cols=512,
    study_desc="",
    accession="",
    study_date=STUDY_DATE,
    study_time=STUDY_TIME,
    series_number=1,
    frame_of_ref_uid=None,
) -> bytes:
    """Build a DICOM P10 byte string for one slice."""

    # Clamp to int16
    arr = np.clip(pixel_array, -32768, 32767).astype(np.int16)

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class
    file_meta.MediaStorageSOPInstanceUID = instance_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.is_implicit_VR = False
    ds.is_little_endian = True

    # Patient
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = "19600101"
    ds.PatientSex = "O"

    # Study
    ds.StudyInstanceUID = study_uid
    ds.StudyDate = study_date
    ds.StudyTime = study_time
    ds.StudyDescription = study_desc
    ds.AccessionNumber = accession
    ds.ReferringPhysicianName = "DEMO^PHYSICIAN"
    ds.StudyID = "1"

    # Series
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.SeriesDescription = series_desc
    ds.Modality = modality

    # Instance
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = instance_uid
    ds.InstanceNumber = slice_idx + 1

    # Image geometry
    ds.Rows = rows
    ds.Columns = cols
    ds.PixelSpacing = [pixel_spacing[0], pixel_spacing[1]]
    ds.SliceThickness = slice_thickness
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0, 0, -slice_idx * slice_thickness]
    if frame_of_ref_uid:
        ds.FrameOfReferenceUID = frame_of_ref_uid

    # Pixel data encoding
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1  # signed

    ds.RescaleIntercept = rescale_intercept
    ds.RescaleSlope = rescale_slope
    ds.WindowCenter = window_center
    ds.WindowWidth = window_width

    ds.PixelData = arr.tobytes()

    buf = io.BytesIO()
    pydicom.dcmwrite(buf, ds)
    return buf.getvalue()


def upload(dcm_bytes: bytes) -> bool:
    import urllib.request, base64
    req = urllib.request.Request(
        f"{ORTHANC_URL}/instances",
        data=dcm_bytes,
        method="POST",
    )
    credentials = base64.b64encode(f"{ORTHANC_USER}:{ORTHANC_PASS}".encode()).decode()
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Content-Type", "application/dicom")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status in (200, 409)
    except Exception as e:
        print(f"    Upload error: {e}", file=sys.stderr)
        return False


def generate_series(name, gen_fn, n_slices, patient_name, patient_id,
                    study_uid, study_desc, modality, sop_class,
                    series_desc, series_number, **kwargs):
    series_uid = make_uid()
    fref_uid = make_uid()
    print(f"  Generating {n_slices} slices: {series_desc}")
    ok = 0
    for i in range(n_slices):
        pixel_array = gen_fn(i, n_slices)
        instance_uid = make_uid()
        dcm = build_ds(
            patient_name=patient_name,
            patient_id=patient_id,
            study_uid=study_uid,
            series_uid=series_uid,
            sop_class=sop_class,
            instance_uid=instance_uid,
            series_desc=series_desc,
            modality=modality,
            slice_idx=i,
            n_slices=n_slices,
            pixel_array=pixel_array,
            frame_of_ref_uid=fref_uid,
            study_desc=study_desc,
            series_number=series_number,
            **kwargs,
        )
        if upload(dcm):
            ok += 1
        if (i + 1) % 10 == 0:
            print(f"    {i+1}/{n_slices} uploaded...")
    print(f"  Done: {ok}/{n_slices} instances stored.")


# ── Image generators ──────────────────────────────────────────────────────────

def ct_chest_slice(i, n):
    """
    Axial CT chest:
    - Outer ellipse = body outline (soft tissue ~50 HU)
    - Lung fields = bilateral low-density ovals (~-700 HU)
    - Heart = central ellipse (~40 HU)
    - Spine = small dense circle (~700 HU)
    - Ribs = thin high-density arcs
    - Vessels = small circles in lungs (~50 HU)
    - Trachea = air lumen in upper slices
    """
    S = 512
    img = np.full((S, S), -1000, dtype=np.float32)  # air outside

    t = i / max(n - 1, 1)  # 0 = apex, 1 = base

    # Body outline (oval torso)
    body_rx = int(170 + 20 * t)
    body_ry = int(140 + 10 * t)
    cx, cy = S // 2, S // 2 + 10
    ellipse(img, cx, cy, body_rx, body_ry, 50)   # soft tissue

    # Subcutaneous fat ring
    fat = np.zeros((S, S), dtype=np.float32)
    ellipse(fat, cx, cy, body_rx - 8, body_ry - 8, 1)
    img[fat == 0] = img[fat == 0]  # no-op, we use a different approach below

    # Spine (posterior)
    spine_cx = cx
    spine_cy = cy + int(80 + 10 * t)
    circle(img, spine_cx, spine_cy, 22, 700)
    circle(img, spine_cx, spine_cy, 14, 200)   # medullary canal

    # Left lung field
    l_cx = cx - int(80 + 5 * t)
    l_cy = cy - int(10 - 15 * t)
    l_rx = int(65 + 10 * t)
    l_ry = int(80 + 15 * t)
    ellipse(img, l_cx, l_cy, l_rx, l_ry, -700)

    # Right lung field (slightly larger)
    r_cx = cx + int(75 + 5 * t)
    r_cy = cy - int(10 - 15 * t)
    r_rx = int(68 + 12 * t)
    r_ry = int(82 + 15 * t)
    ellipse(img, r_cx, r_cy, r_rx, r_ry, -700)

    # Heart (visible in middle third of scan)
    if 0.25 < t < 0.85:
        h_scale = math.sin((t - 0.25) / 0.6 * math.pi)
        h_rx = int(55 * h_scale)
        h_ry = int(65 * h_scale)
        h_cx = cx - 15
        h_cy = cy - 5
        ellipse(img, h_cx, h_cy, h_rx, h_ry, 55)
        # Cardiac chambers (lower density blood pool)
        if h_rx > 20:
            ellipse(img, h_cx - 10, h_cy - 5, h_rx // 3, h_ry // 3, 35)
            ellipse(img, h_cx + 10, h_cy + 5, h_rx // 3, h_ry // 3, 35)

    # Trachea / carina (upper slices)
    if t < 0.4:
        tr_r = int(12 * (1 - t / 0.4))
        circle(img, cx + 5, cy - 30, tr_r, -950)
        if t > 0.25:  # carina bifurcation
            circle(img, cx - 18, cy - 25, 8, -950)
            circle(img, cx + 28, cy - 25, 8, -950)

    # Pulmonary vessels (bright dots in lung fields)
    rng = np.random.RandomState(i)
    for _ in range(25):
        vx = int(l_cx + rng.uniform(-l_rx * 0.7, l_rx * 0.7))
        vy = int(l_cy + rng.uniform(-l_ry * 0.7, l_ry * 0.7))
        circle(img, vx, vy, rng.randint(2, 6), 60)

    for _ in range(27):
        vx = int(r_cx + rng.uniform(-r_rx * 0.7, r_rx * 0.7))
        vy = int(r_cy + rng.uniform(-r_ry * 0.7, r_ry * 0.7))
        circle(img, vx, vy, rng.randint(2, 6), 60)

    # Aorta
    ao_cx = cx - 30
    ao_cy = cy - 20
    circle(img, ao_cx, ao_cy, 14, 55)
    circle(img, ao_cx, ao_cy, 10, 30)  # blood pool

    # Add realistic noise
    img += noise((S, S), sigma=15, rng=rng)
    return img


def ct_abdomen_slice(i, n):
    """Axial CT abdomen: liver, kidneys, aorta, bowel, spine."""
    S = 512
    img = np.full((S, S), -1000, dtype=np.float32)
    t = i / max(n - 1, 1)
    rng = np.random.RandomState(i + 1000)

    cx, cy = S // 2, S // 2

    # Body
    ellipse(img, cx, cy, 175, 150, 50)

    # Spine
    circle(img, cx, cy + 85, 25, 750)
    circle(img, cx, cy + 85, 16, 250)

    # Liver (right side, large, upper slices)
    if t < 0.7:
        liv_scale = 1 - t * 0.4
        l_cx = cx + 60
        l_cy = cy - 20
        ellipse(img, l_cx, l_cy, int(90 * liv_scale), int(70 * liv_scale), 60)

    # Stomach (left, air + fluid)
    st_cx = cx - 55
    st_cy = cy - 30
    ellipse(img, st_cx, st_cy, 35, 30, 30)    # wall
    ellipse(img, st_cx, st_cy, 25, 20, -500)  # air/fluid

    # Spleen (left, upper-mid)
    if 0.1 < t < 0.7:
        sp_cx = cx - 85
        sp_cy = cy - 15
        sp_scale = math.sin((t - 0.1) / 0.6 * math.pi)
        ellipse(img, sp_cx, sp_cy, int(50 * sp_scale), int(40 * sp_scale), 55)

    # Kidneys (bilateral, mid slices)
    if 0.3 < t < 0.8:
        k_scale = math.sin((t - 0.3) / 0.5 * math.pi)
        for sign, k_cx in [(-1, cx - 70), (1, cx + 65)]:
            k_cy = cy + 10
            kr = int(30 * k_scale)
            ellipse(img, k_cx, k_cy, kr, int(kr * 1.5), 40)
            # Renal pelvis
            circle(img, k_cx, k_cy, max(1, int(kr * 0.4)), 10)

    # Aorta
    circle(img, cx - 10, cy + 60, 12, 55)
    circle(img, cx - 10, cy + 60, 8, 25)

    # IVC
    circle(img, cx + 18, cy + 60, 16, 45)
    circle(img, cx + 18, cy + 60, 11, 25)

    # Bowel loops (lower slices)
    if t > 0.4:
        for _ in range(12):
            bx = int(cx + rng.uniform(-120, 120))
            by_ = int(cy + rng.uniform(-80, 60))
            br = rng.randint(10, 22)
            ellipse(img, bx, by_, br, int(br * 0.8), 40)
            ellipse(img, bx, by_, br - 4, int((br - 4) * 0.8), -600)

    img += noise((S, S), sigma=12, rng=rng)
    return img


def mri_brain_slice(i, n):
    """
    Axial MRI brain (T1-weighted):
    - Skull = bright ring (~800)
    - White matter = bright (~700)
    - Gray matter cortex = slightly less bright (~550)
    - Ventricles = dark CSF (~50)
    - Subcortical structures
    """
    S = 512
    img = np.zeros((S, S), dtype=np.float32)
    t = i / max(n - 1, 1)  # 0 = vertex, 1 = base
    rng = np.random.RandomState(i + 2000)

    cx, cy = S // 2, S // 2

    # Skull (bone-suppressed in T1; appears as dark outer ring)
    brain_rx = int(160 - 20 * abs(t - 0.5) * 2)
    brain_ry = int(185 - 30 * abs(t - 0.5) * 2)
    ellipse(img, cx, cy, brain_rx + 12, brain_ry + 12, 200)  # skull
    ellipse(img, cx, cy, brain_rx + 6, brain_ry + 6, 50)    # scalp fat
    ellipse(img, cx, cy, brain_rx, brain_ry, 700)             # white matter

    # Cortical gray matter (thin outer ring)
    gm_mask = np.zeros((S, S), dtype=np.float32)
    ellipse(gm_mask, cx, cy, brain_rx, brain_ry, 1)
    inner_mask = np.zeros((S, S), dtype=np.float32)
    ellipse(inner_mask, cx, cy, brain_rx - 18, brain_ry - 18, 1)
    img[(gm_mask == 1) & (inner_mask == 0)] = 550

    # Sulci (dark CSF-filled grooves) — random radial lines
    for angle in np.linspace(0, 2 * math.pi, 24, endpoint=False):
        sx = int(cx + (brain_rx - 10) * math.cos(angle))
        sy = int(cy + (brain_ry - 10) * math.sin(angle))
        circle(img, sx, sy, 3, 80)

    # Lateral ventricles (mid slices)
    if 0.25 < t < 0.8:
        v_scale = math.sin((t - 0.25) / 0.55 * math.pi)
        # Left ventricle
        ellipse(img, cx - 30, cy - 10, int(30 * v_scale), int(15 * v_scale), 80)
        # Right ventricle
        ellipse(img, cx + 30, cy - 10, int(30 * v_scale), int(15 * v_scale), 80)
        # Third ventricle
        ellipse(img, cx, cy + 5, 6, int(20 * v_scale), 80)

    # Corpus callosum (bright white matter bridge, mid slices)
    if 0.3 < t < 0.65:
        ellipse(img, cx, cy - 15, 50, 8, 750)

    # Basal ganglia (slightly brighter subcortical nuclei)
    if 0.35 < t < 0.7:
        bg_scale = math.sin((t - 0.35) / 0.35 * math.pi)
        for sign, offset in [(-1, -40), (1, 40)]:
            circle(img, cx + offset, cy + 10, int(20 * bg_scale), 620)
            circle(img, cx + offset + sign * 15, cy + 5, int(12 * bg_scale), 600)

    # Cerebellum (lower slices, posterior)
    if t > 0.6:
        cb_scale = (t - 0.6) / 0.4
        ellipse(img, cx, cy + 80, int(80 * cb_scale), int(50 * cb_scale), 680)
        ellipse(img, cx, cy + 80, int(70 * cb_scale), int(40 * cb_scale), 720)
        # Cerebellar folia (fine lines)
        for k in range(8):
            angle = math.pi * k / 8
            fx = int(cx + 60 * cb_scale * math.cos(angle))
            fy = int(cy + 80 + 35 * cb_scale * math.sin(angle))
            circle(img, fx, fy, 2, 500)

    # Brainstem
    if t > 0.5:
        bs_r = int(30 * (t - 0.5) / 0.5)
        ellipse(img, cx, cy + 50, bs_r, int(bs_r * 1.3), 660)

    # Mild T1 noise
    img += noise((S, S), sigma=20, rng=rng)
    img = np.clip(img, 0, 1000)
    return img


def mri_spine_slice(i, n):
    """
    Sagittal MRI spine (T2):
    - Vertebral bodies = dark (cortical bone)
    - Discs = bright (high water content)
    - Spinal cord = intermediate
    - CSF = very bright
    """
    S = 512
    img = np.zeros((S, S), dtype=np.float32)
    rng = np.random.RandomState(i + 3000)

    cx = S // 2
    n_vert = 7  # show 7 vertebral levels

    for v in range(n_vert):
        top_y = 30 + v * 68
        body_h = 45
        disc_h = 12
        body_y = top_y + body_h // 2

        # Vertebral body (cortical bone outer, cancellous inner)
        ellipse(img, cx, body_y, 55, body_h // 2, 300)          # cortical bone
        ellipse(img, cx, body_y, 44, body_h // 2 - 5, 600)      # cancellous (bright)
        ellipse(img, cx, body_y, 20, body_h // 2 - 12, 400)     # central (slightly darker)

        # Spinous process (posterior)
        sp_y = body_y
        sp_x = cx + 80
        ellipse(img, sp_x, sp_y, 20, 15, 280)

        # Pedicles
        ellipse(img, cx + 55, sp_y, 10, 8, 280)
        ellipse(img, cx - 55, sp_y, 10, 8, 280)

        # Intervertebral disc (bright in T2)
        if v < n_vert - 1:
            disc_y = top_y + body_h + disc_h // 2
            ellipse(img, cx, disc_y, 50, disc_h // 2, 850)    # nucleus pulposus
            ellipse(img, cx, disc_y, 55, disc_h // 2, 400)    # annulus fibrosus
            # Mild disc degeneration on some levels
            if v in (2, 4):
                ellipse(img, cx, disc_y, 45, disc_h // 2 - 2, 500)

    # Spinal canal / CSF
    ellipse(img, cx, S // 2, 10, S // 2 - 20, 900)  # CSF column

    # Spinal cord (within CSF)
    ellipse(img, cx, S // 2, 6, S // 2 - 30, 550)

    # Paravertebral soft tissue
    for side in [-1, 1]:
        ellipse(img, cx + side * 85, S // 2, 25, S // 2 - 40, 200)

    img += noise((S, S), sigma=18, rng=rng)
    img = np.clip(img, 0, 1000)
    return img


def pet_ct_slice(i, n):
    """
    PET-CT (SUV map overlaid on CT):
    Simulates a whole-body PET with a hot lesion in the right lung.
    Stored as a NM (nuclear medicine) image with SUV-like values.
    """
    S = 256  # PET typically lower resolution
    img = np.zeros((S, S), dtype=np.float32)
    t = i / max(n - 1, 1)
    rng = np.random.RandomState(i + 4000)

    cx, cy = S // 2, S // 2

    # Body outline (faint background uptake)
    body_rx, body_ry = 90, 75
    ellipse(img, cx, cy, body_rx, body_ry, 800)   # background ~0.8 SUV

    # Physiologic uptake: brain (top slices)
    if t < 0.25:
        brain_scale = 1 - t / 0.25
        circle(img, cx, cy - 20, int(55 * brain_scale), 8000)  # brain ~8 SUV

    # Liver (mid slices, moderate uptake)
    if 0.35 < t < 0.75:
        liv_scale = math.sin((t - 0.35) / 0.4 * math.pi)
        ellipse(img, cx + 30, cy - 10, int(45 * liv_scale), int(35 * liv_scale), 2500)

    # Kidneys / bladder (high uptake — FDG excreted)
    if 0.55 < t < 0.85:
        k_scale = math.sin((t - 0.55) / 0.3 * math.pi)
        for kx in [cx - 35, cx + 30]:
            circle(img, kx, cy + 5, int(18 * k_scale), 4000)

    # HOT LESION — right lung nodule, 3 cm, SUV ~12
    lesion_t_center = 0.35
    lesion_sigma = 0.08
    lesion_intensity = 12000 * math.exp(-((t - lesion_t_center) ** 2) / (2 * lesion_sigma ** 2))
    if lesion_intensity > 500:
        lesion_r = max(3, int(14 * (lesion_intensity / 12000) ** 0.5))
        circle(img, cx + 40, cy - 20, lesion_r, lesion_intensity)

    # Noise
    img += np.abs(noise((S, S), sigma=200, rng=rng))
    img = np.clip(img, 0, 15000)
    return img


# ── Study / patient definitions ───────────────────────────────────────────────

PATIENTS = [
    {
        "patient_name": "MUELLER^ANNA",
        "patient_id": "P001",
        "study_desc": "CT Chest w/o Contrast",
        "accession": "ACC001",
        "date_offset": 0,
        "series": [
            {
                "desc": "Axial CT Chest - Lung Window",
                "modality": "CT",
                "sop_class": CTImageStorage,
                "gen": ct_chest_slice,
                "n": 60,
                "window_center": -600,
                "window_width": 1600,
                "rescale_intercept": -1024,
                "pixel_spacing": (0.66, 0.66),
                "slice_thickness": 2.5,
                "number": 1,
            },
            {
                "desc": "Axial CT Chest - Mediastinum Window",
                "modality": "CT",
                "sop_class": CTImageStorage,
                "gen": ct_chest_slice,
                "n": 60,
                "window_center": 40,
                "window_width": 400,
                "rescale_intercept": -1024,
                "pixel_spacing": (0.66, 0.66),
                "slice_thickness": 2.5,
                "number": 2,
            },
        ],
    },
    {
        "patient_name": "SCHMIDT^PETER",
        "patient_id": "P002",
        "study_desc": "CT Abdomen/Pelvis w Contrast",
        "accession": "ACC002",
        "date_offset": -3,
        "series": [
            {
                "desc": "Axial CT Abdomen - Portal Venous Phase",
                "modality": "CT",
                "sop_class": CTImageStorage,
                "gen": ct_abdomen_slice,
                "n": 45,
                "window_center": 60,
                "window_width": 350,
                "rescale_intercept": -1024,
                "pixel_spacing": (0.78, 0.78),
                "slice_thickness": 3.0,
                "number": 1,
            },
        ],
    },
    {
        "patient_name": "WEBER^SOPHIE",
        "patient_id": "P003",
        "study_desc": "MRI Brain w and w/o Gadolinium",
        "accession": "ACC003",
        "date_offset": -7,
        "series": [
            {
                "desc": "Axial T1 Pre-contrast",
                "modality": "MR",
                "sop_class": MRImageStorage,
                "gen": mri_brain_slice,
                "n": 30,
                "window_center": 500,
                "window_width": 800,
                "rescale_intercept": 0,
                "pixel_spacing": (0.5, 0.5),
                "slice_thickness": 4.0,
                "number": 1,
            },
            {
                "desc": "Axial T1 Post-contrast",
                "modality": "MR",
                "sop_class": MRImageStorage,
                "gen": lambda i, n: mri_brain_slice(i, n) * 1.15,  # contrast enhancement
                "n": 30,
                "window_center": 550,
                "window_width": 800,
                "rescale_intercept": 0,
                "pixel_spacing": (0.5, 0.5),
                "slice_thickness": 4.0,
                "number": 2,
            },
        ],
    },
    {
        "patient_name": "HOFFMANN^THOMAS",
        "patient_id": "P004",
        "study_desc": "MRI Lumbar Spine w/o Contrast",
        "accession": "ACC004",
        "date_offset": -14,
        "series": [
            {
                "desc": "Sagittal T2 Lumbar Spine",
                "modality": "MR",
                "sop_class": MRImageStorage,
                "gen": mri_spine_slice,
                "n": 20,
                "window_center": 500,
                "window_width": 900,
                "rescale_intercept": 0,
                "pixel_spacing": (0.4, 0.4),
                "slice_thickness": 3.5,
                "number": 1,
            },
        ],
    },
    {
        "patient_name": "BRAUN^ELENA",
        "patient_id": "P005",
        "study_desc": "PET-CT Whole Body",
        "accession": "ACC005",
        "date_offset": -1,
        "series": [
            {
                "desc": "PET Whole Body FDG",
                "modality": "PT",
                "sop_class": NM_IMAGE_STORAGE,
                "gen": pet_ct_slice,
                "n": 40,
                "window_center": 4000,
                "window_width": 8000,
                "rescale_intercept": 0,
                "pixel_spacing": (3.5, 3.5),
                "slice_thickness": 5.0,
                "rows": 256,
                "cols": 256,
                "number": 1,
            },
        ],
    },
]


# ── Main ──────────────────────────────────────────────────────────────────────

def wait_for_orthanc():
    import base64
    print(f"Waiting for Orthanc at {ORTHANC_URL} ...", end="", flush=True)
    cred = base64.b64encode(f"{ORTHANC_USER}:{ORTHANC_PASS}".encode()).decode()
    for _ in range(30):
        try:
            req = urllib.request.Request(f"{ORTHANC_URL}/system")
            req.add_header("Authorization", f"Basic {cred}")
            with urllib.request.urlopen(req, timeout=5):
                print(" ready.")
                return
        except Exception:
            print(".", end="", flush=True)
            time.sleep(2)
    sys.exit("\nOrthanc not reachable. Is docker compose up?")


def main():
    wait_for_orthanc()
    print()

    for p in PATIENTS:
        date = (NOW + timedelta(days=p["date_offset"])).strftime("%Y%m%d")
        study_uid = make_uid()
        print(f"Patient: {p['patient_name']}  [{p['study_desc']}]")

        for s in p["series"]:
            rows = s.get("rows", 512)
            cols = s.get("cols", 512)
            generate_series(
                name=p["patient_name"],
                gen_fn=s["gen"],
                n_slices=s["n"],
                patient_name=p["patient_name"],
                patient_id=p["patient_id"],
                study_uid=study_uid,
                study_desc=p["study_desc"],
                modality=s["modality"],
                sop_class=s["sop_class"],
                series_desc=s["desc"],
                series_number=s["number"],
                window_center=s["window_center"],
                window_width=s["window_width"],
                rescale_intercept=s.get("rescale_intercept", 0),
                pixel_spacing=(s["pixel_spacing"][0], s["pixel_spacing"][1]),
                slice_thickness=s["slice_thickness"],
                rows=rows,
                cols=cols,
                accession=p["accession"],
                study_date=date,
            )
        print()

    import base64, json
    cred = base64.b64encode(f"{ORTHANC_USER}:{ORTHANC_PASS}".encode()).decode()
    req = urllib.request.Request(f"{ORTHANC_URL}/statistics")
    req.add_header("Authorization", f"Basic {cred}")
    with urllib.request.urlopen(req) as r:
        stats = json.loads(r.read())
    print(f"Done. Orthanc now has {stats['CountStudies']} studies, "
          f"{stats['CountInstances']} instances.")
    print(f"Viewer: http://localhost:4200")
    print(f"Orthanc explorer: {ORTHANC_URL}/app/explorer.html")


if __name__ == "__main__":
    main()
