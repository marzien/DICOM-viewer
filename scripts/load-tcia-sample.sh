#!/usr/bin/env bash
# load-tcia-sample.sh
# Downloads real DICOM data from public sources and uploads to Orthanc.
# Sources tried in order:
#   1. TCIA (The Cancer Imaging Archive) public REST API — real CT series, no login
#   2. Orthanc UCLouvain official test ZIP
#   3. Pydicom / Rubo Medical individual sample files

set -euo pipefail

ORTHANC_URL="${ORTHANC_URL:-http://localhost:8042}"
ORTHANC_USER="${ORTHANC_USER:-admin}"
ORTHANC_PASS="${ORTHANC_PASS:-orthanc}"
WORK_DIR="$(mktemp -d)"
TCIA_API="https://services.cancerimagingarchive.net/nbia-api/services/v1"

log()     { echo "[$(date +%T)] $*"; }
log_sub() { echo "[$(date +%T)]   $*"; }
die()     { log "ERROR: $*"; exit 1; }
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

# ── 1. Wait for Orthanc ───────────────────────────────────────────────────────
log "Waiting for Orthanc at $ORTHANC_URL ..."
for i in $(seq 1 30); do
  if curl -sf -u "$ORTHANC_USER:$ORTHANC_PASS" "$ORTHANC_URL/system" >/dev/null 2>&1; then
    log "Orthanc is ready."
    break
  fi
  [ "$i" -eq 30 ] && die "Orthanc did not become ready in 60 s."
  sleep 2
done

# ── helper: upload every DICOM file found recursively under a directory ───────
upload_dir() {
  local dir="$1"
  local count=0 failed=0
  while IFS= read -r -d '' f; do
    http_code=$(curl -sf -u "$ORTHANC_USER:$ORTHANC_PASS" \
      -X POST "$ORTHANC_URL/instances" \
      --data-binary "@$f" \
      -w "%{http_code}" -o /dev/null 2>/dev/null || echo "000")
    if [[ "$http_code" =~ ^(200|409)$ ]]; then
      count=$((count + 1))
    else
      failed=$((failed + 1))
    fi
  done < <(find "$dir" \( -iname "*.dcm" -o -iname "*.dicom" -o -iname "IM*" \) -type f -print0 2>/dev/null)
  log_sub "Uploaded $count instance(s) ($failed failed)."
  echo "$count"
}

LOADED=0

# ── 2. TCIA public REST API ───────────────────────────────────────────────────
# RIDER Lung CT is an openly accessible collection (no TCIA account required).
# We query the API for a series, then download its ZIP.
log "=== Source 1: TCIA RIDER Lung CT (public, no login) ==="

SERIES_JSON=$(curl -sf --max-time 20 \
  "$TCIA_API/getSeries?Collection=RIDER+Lung+CT&Modality=CT&maxReturn=3" \
  2>/dev/null || echo "[]")

SERIES_UID=$(echo "$SERIES_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
# pick the series with fewest images so the download is manageable
best = min(data, key=lambda s: int(s.get('ImageCount','9999')), default=None)
print(best['SeriesInstanceUID'] if best else '')
" 2>/dev/null || echo "")

if [ -n "$SERIES_UID" ]; then
  IMAGE_COUNT=$(echo "$SERIES_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
best = min(data, key=lambda s: int(s.get('ImageCount','9999')), default=None)
print(best.get('ImageCount','?') if best else '?')
" 2>/dev/null || echo "?")
  log "Downloading series $SERIES_UID ($IMAGE_COUNT images)..."
  log "This is real CT data — may be 50–200 MB, please wait..."

  mkdir -p "$WORK_DIR/tcia"
  http_code=$(curl -sf --max-time 600 \
    -u "nbia_guest:nbia_guest" \
    "$TCIA_API/getImage?SeriesInstanceUID=$SERIES_UID" \
    -o "$WORK_DIR/tcia/series.zip" \
    -w "%{http_code}" 2>/dev/null || echo "000")

  if [ "$http_code" = "200" ] && [ -s "$WORK_DIR/tcia/series.zip" ]; then
    SIZE=$(du -sh "$WORK_DIR/tcia/series.zip" | cut -f1)
    log "Downloaded $SIZE ZIP. Extracting..."
    unzip -q "$WORK_DIR/tcia/series.zip" -d "$WORK_DIR/tcia/extracted" 2>/dev/null || true
    LOADED=$(upload_dir "$WORK_DIR/tcia/extracted")
    [ "$LOADED" -gt 0 ] && log "SUCCESS: Loaded $LOADED instances from TCIA." \
                        || log "Extraction yielded no DICOM files, trying next source."
  else
    log "TCIA download failed (HTTP $http_code), trying next source."
  fi
else
  log "TCIA API unreachable or returned no series, trying next source."
fi

# ── 3. Orthanc UCLouvain official test ZIP ────────────────────────────────────
if [ "$LOADED" -eq 0 ]; then
  log "=== Source 2: Orthanc UCLouvain test data ==="
  mkdir -p "$WORK_DIR/orthanc"
  http_code=$(curl -sfL --max-time 120 \
    "https://orthanc.uclouvain.be/downloads/orthanctest.zip" \
    -o "$WORK_DIR/orthanc/orthanctest.zip" \
    -w "%{http_code}" 2>/dev/null || echo "000")

  if [ "$http_code" = "200" ] && [ -s "$WORK_DIR/orthanc/orthanctest.zip" ]; then
    SIZE=$(du -sh "$WORK_DIR/orthanc/orthanctest.zip" | cut -f1)
    log "Downloaded $SIZE. Extracting..."
    unzip -q "$WORK_DIR/orthanc/orthanctest.zip" -d "$WORK_DIR/orthanc/extracted" 2>/dev/null || true
    LOADED=$(upload_dir "$WORK_DIR/orthanc/extracted")
    [ "$LOADED" -gt 0 ] && log "SUCCESS: Loaded $LOADED instances from Orthanc test data." \
                        || log "No DICOM files found in ZIP, trying next source."
  else
    log "Orthanc test ZIP unavailable (HTTP $http_code), trying next source."
  fi
fi

# ── 4. Pydicom sample files + Rubo Medical (small but always available) ───────
if [ "$LOADED" -eq 0 ]; then
  log "=== Source 3: Pydicom sample files ==="
  mkdir -p "$WORK_DIR/pydicom"

  BASE="https://github.com/pydicom/pydicom/raw/main/tests/test_files"
  for fname in \
    CT_small.dcm \
    MR_small.dcm \
    CT_MONO2_16_brain.dcm \
    CT_MONO2_16_ankle.dcm \
    MR_SIEMENS_forceLoad.dcm \
    JPEG2000.dcm \
    JPGLosslessP14SV1_1s_1f_8b.dcm; do
    code=$(curl -sfL --max-time 30 "$BASE/$fname" \
      -o "$WORK_DIR/pydicom/$fname" -w "%{http_code}" 2>/dev/null || echo "000")
    [ "$code" = "200" ] && log_sub "Downloaded $fname" || log_sub "Skipped $fname (HTTP $code)"
  done

  LOADED=$(upload_dir "$WORK_DIR/pydicom")

  # Also try Rubo Medical sample CT ZIP (~15 slices)
  log "=== Source 3b: Rubo Medical sample CT ==="
  mkdir -p "$WORK_DIR/rubo"
  code=$(curl -sfL --max-time 60 \
    "https://www.rubomedical.com/dicom_files/dicom_viewer_0002.zip" \
    -o "$WORK_DIR/rubo/rubo.zip" -w "%{http_code}" 2>/dev/null || echo "000")
  if [ "$code" = "200" ] && [ -s "$WORK_DIR/rubo/rubo.zip" ]; then
    unzip -q "$WORK_DIR/rubo/rubo.zip" -d "$WORK_DIR/rubo/extracted" 2>/dev/null || true
    n=$(upload_dir "$WORK_DIR/rubo/extracted")
    LOADED=$((LOADED + n))
  else
    log_sub "Rubo Medical unavailable (HTTP $code)"
  fi
fi

# ── 5. Summary ────────────────────────────────────────────────────────────────
echo ""
STUDY_COUNT=$(curl -sf -u "$ORTHANC_USER:$ORTHANC_PASS" "$ORTHANC_URL/statistics" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('CountStudies',0))" \
  2>/dev/null || echo "unknown")

log "Done. $STUDY_COUNT study/studies now in Orthanc."
log "Orthanc explorer: $ORTHANC_URL/app/explorer.html"
log "Viewer:           http://localhost:4200"
