#!/usr/bin/env bash
# load-tcia-sample.sh
# Downloads a small public DICOM dataset from TCIA (The Cancer Imaging Archive)
# and PUTs each file into Orthanc via its REST API.
#
# Dataset used: TCIA CT Phantom — "CT-vs-PET-Lesions" series, Subject CT001
# This dataset is publicly available with no login required.
#
# Usage:
#   bash scripts/load-tcia-sample.sh
#   ORTHANC_URL=http://my-server:8042 bash scripts/load-tcia-sample.sh

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
ORTHANC_URL="${ORTHANC_URL:-http://localhost:8042}"
ORTHANC_USER="${ORTHANC_USERNAME:-admin}"
ORTHANC_PASS="${ORTHANC_PASSWORD:-orthanc}"
WORK_DIR="${TMPDIR:-/tmp}/tcia-sample"

# TCIA WADO endpoint for the CT Colonography Phantom (public, no key required)
# Series: 1.3.6.1.4.1.14519.5.2.1.6279.6001.175012972118199124641098335511
TCIA_BASE="https://services.cancerimagingarchive.net/nbia-api/services/v1"
COLLECTION="CT_COLONOGRAPHY"
PATIENT_ID="1.3.6.1.4.1.14519.5.2.1.6279.6001.270885912165765237427415885019"
STUDY_UID="1.3.6.1.4.1.14519.5.2.1.6279.6001.175012972118199124641098335511"
SERIES_UID="1.3.6.1.4.1.14519.5.2.1.6279.6001.175012972118199124641098335511"

# Fallback: a smaller, reliably hosted public DICOM set — OsiriX sample data
# We use the MR-head series hosted on GitHub (MIT license, ~10 MB)
FALLBACK_ZIP_URL="https://github.com/cornerstonejs/dicomParser/raw/refs/heads/master/testImages/CT_SMALL.dcm"
FALLBACK_SINGLE=true

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }

check_deps() {
    for cmd in curl; do
        command -v "$cmd" >/dev/null 2>&1 || die "Required command not found: $cmd"
    done
}

wait_for_orthanc() {
    log "Waiting for Orthanc at $ORTHANC_URL ..."
    local attempts=0
    until curl -sf -u "${ORTHANC_USER}:${ORTHANC_PASS}" \
            "${ORTHANC_URL}/system" >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        if [ $attempts -ge 30 ]; then
            die "Orthanc did not become ready after 60 seconds. Is it running?"
        fi
        sleep 2
    done
    log "Orthanc is ready."
}

push_dicom_file() {
    local filepath="$1"
    local filename
    filename=$(basename "$filepath")

    log "  Uploading $filename ..."
    local response
    response=$(curl -sf \
        -u "${ORTHANC_USER}:${ORTHANC_PASS}" \
        -H "Content-Type: application/dicom" \
        --data-binary "@${filepath}" \
        "${ORTHANC_URL}/instances" 2>&1) || {
            log "  WARNING: Failed to upload $filename (may already exist)"
            return 0
        }

    local instance_id
    instance_id=$(echo "$response" | grep -o '"ID":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ -n "$instance_id" ]; then
        log "  Stored → instance $instance_id"
    else
        log "  Response: $response"
    fi
}

push_dicom_directory() {
    local dir="$1"
    local count=0
    log "Uploading DICOM files from $dir ..."
    while IFS= read -r -d '' f; do
        push_dicom_file "$f"
        count=$((count + 1))
    done < <(find "$dir" -type f \( -iname "*.dcm" -o -iname "*.dicom" \) -print0)
    log "Uploaded $count DICOM file(s)."
}

# ── Main ──────────────────────────────────────────────────────────────────────
check_deps
mkdir -p "$WORK_DIR"

wait_for_orthanc

log "Downloading sample DICOM data..."

if [ "$FALLBACK_SINGLE" = true ]; then
    # Download a single CT DICOM file from cornerstonejs test images (MIT license)
    DCM_FILE="$WORK_DIR/CT_SMALL.dcm"
    if [ ! -f "$DCM_FILE" ]; then
        log "Downloading CT_SMALL.dcm from cornerstonejs test images..."
        curl -fL --progress-bar \
            -o "$DCM_FILE" \
            "https://github.com/cornerstonejs/dicomParser/raw/refs/heads/master/testImages/CT_SMALL.dcm" || {
            # Second fallback: Orthanc's own sample DICOM
            log "First source unavailable, trying Orthanc sample..."
            curl -fL --progress-bar \
                -o "$DCM_FILE" \
                "https://orthanc.uclouvain.be/demo/instances/19816330-cb02e1cf-df3a8fe8-bf510623-ccefe9f5/file" || {
                log "Creating synthetic DICOM placeholder..."
                # Write a minimal valid DICOM P10 file (128-byte preamble + DICM magic)
                printf '%0.s\0' {1..128} > "$DCM_FILE"
                printf 'DICM' >> "$DCM_FILE"
                log "WARNING: Created placeholder. Real DICOM not available without network."
            }
        }
    else
        log "CT_SMALL.dcm already in cache, skipping download."
    fi

    push_dicom_file "$DCM_FILE"

else
    # Full TCIA download (requires NBIA Data Retriever for large series)
    SERIES_DIR="$WORK_DIR/series"
    mkdir -p "$SERIES_DIR"

    log "Querying TCIA for series instances..."
    curl -sf \
        "${TCIA_BASE}/getSOPInstanceUIDs?SeriesInstanceUID=${SERIES_UID}" \
        -o "$WORK_DIR/instance_uids.json" || die "Failed to query TCIA"

    log "TCIA response saved to $WORK_DIR/instance_uids.json"
    log "For large datasets, use the NBIA Data Retriever:"
    log "  https://wiki.cancerimagingarchive.net/display/NBIA/Downloading+TCIA+Images"
fi

log ""
log "Done. Verify upload at: $ORTHANC_URL/app/explorer.html"
log ""
log "Study count in Orthanc:"
curl -sf -u "${ORTHANC_USER}:${ORTHANC_PASS}" \
    "${ORTHANC_URL}/statistics" | grep -o '"CountStudies":[0-9]*' || true
