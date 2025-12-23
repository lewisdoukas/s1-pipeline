# Sentinel-1 Pipelines (ASF / CDSE) → (pyroSAR or GDAL) → AOI Clips

End-to-end Python pipelines for **searching, downloading, and preprocessing Sentinel-1 GRD (VV+VH)** for **data fusion / GeoAI workflows**.

This repo intentionally supports **multiple backends**:

- **pyroSAR + SNAP** for “RTC-style” processing (calibration / noise removal / terrain correction via SNAP geocode)
- **GDAL-only** for fast **GCP-based geocoding + bbox clipping** (no RTC)

---

## 🚀 Features

- 🔍 Search Sentinel-1 GRD (IW, VV+VH)
- 📦 Download **SAFE.zip** from **ASF** or **CDSE**
- 🛰️ Process with **pyroSAR + SNAP** (pyroSAR pipelines)
- ⚡ Fast AOI extraction with **GDAL Warp (TPS from GCPs)** (GDAL pipelines)
- ✂️ Clip outputs to `bbox4326 = [minLon, minLat, maxLon, maxLat]`
- ⏱️ Runtime measurement

---

## 🧭 Pipelines in this repo

The entry point is `main.py`, which selects one of:

```python
pipeline in ["ASF", "CDSE", "GDAL", "COG"]
```

### 1) `ASF` → `asf_pyrosar.py`

\*\*ASF search → download SAFE.zip → pyroSAR(SNAP) geocode → AOI subset/clip

Use this when you want ASF as the data source and SNAP-based processing.

---

### 2) `CDSE` → `cdse_pyrosar.py`

\*\*CDSE search → download SAFE.zip → pyroSAR(SNAP) geocode → AOI subset/clip

Use this when you want CDSE as the data source but still want SNAP/pyroSAR processing.

---

### 3) `GDAL` → `cdse_gdal.py`

**CDSE SAFE.zip → extract measurement TIFFs (VV/VH) → GDAL Warp (TPS from GCPs) → bbox clip (EPSG:4326)**

This is the “lightweight” branch:

- ✅ Fast AOI extraction
- ✅ No SNAP dependency
- ❌ No RTC / no calibration / no terrain correction

How it works:

1. Download SAFE.zip from CDSE (via helper functions)
2. Unzip SAFE locally
3. Read:

   - `SAFE/measurement/*-vv-*.tiff`
   - `SAFE/measurement/*-vh-*.tiff`

4. Run `warp_gcps_clip()` (GDAL TPS warp + bbox clip)

Outputs go to `<workdir>/dist/`.

---

### 4) `COG` → `cog_gdal.py`

**STAC → EOData S3 download of VV/VH COGs → GDAL Warp (TPS from GCPs) → bbox clip (EPSG:4326)**

What it actually does:

1. Uses **STAC** (`pystac_client`) to find the **latest Sentinel-1 GRD item** within the date range / AOI logic used by the script.
2. Reads STAC asset `href`s for `vv` and `vh`, which are `s3://eodata/...`
3. Uses **boto3** to download those VV/VH COGs from:

   - bucket: `eodata`
   - endpoint: `https://eodata.dataspace.copernicus.eu`

4. Runs `warp_gcps_clip()` to clip to `bbox4326`

So the “COG pipeline” is:

- ✅ remote COG download (S3)
- ✅ GDAL-only warp+clip
- ❌ no SAFE.zip required
- ❌ no RTC

**Credentials required**: AWS-style keys for EOData S3 access (see Config below).

---

## 🧠 Processing Logic (High Level)

### pyroSAR pipelines (ASF / CDSE)

- Search → SAFE.zip download → pyroSAR identify/geocode via SNAP
- Typical SNAP geocode chain is “RTC-style” (depends on your SNAP graph/options)
- Output VV/VH in target CRS, then clip/compose as implemented

### GDAL pipelines (GDAL / COG)

- GDAL Warp uses **GCP-based Thin Plate Spline (TPS)**:

  - `tps=True`
  - `srcSRS=EPSG:4326`, `dstSRS=EPSG:4326`
  - `outputBounds=bbox4326`

- Outputs are clipped VV/VH GeoTIFFs in EPSG:4326

> Note: GDAL pipelines do **not** produce RTC. They are intended for fast ML feature extraction / fusion signals.

---

## 📦 Installation

```bash
pip install -r requirements.txt
```

You will need:

- GDAL installed with Python bindings (`osgeo`)
- For pyroSAR pipelines: SNAP installed and configured

---

## 🔐 Configuration

This repo expects a `config.py` with credentials (imported by scripts).

### CDSE

Used by CDSE download helpers:

```python
CDSE_USERNAME = "..."
CDSE_PASSWORD = "..."
```

### EOData S3 (used by `cog_gdal.py`)

```python
AWS_ACCESS_KEY_ID = "..."
AWS_SECRET_ACCESS_KEY = "..."
```

EOData endpoint is:

- `https://eodata.dataspace.copernicus.eu`

### Earthdata (used by `asf_pyrosar.py`)

```python
EARTHDATA_USERNAME = "..."
EARTHDATA_PASSWORD = "..."
```

---

## ▶️ Usage

### Run via `main.py`

Edit in `main.py`:

- `bbox4326`
- `date_start`, `date_end`
- `target_crs` (pyroSAR pipelines may use it; GDAL warp in helpers currently targets EPSG:4326)
- `pipeline`

Then run:

```bash
python main.py
```

---

## 📂 Outputs

Each run writes into a timestamped `workdir`, e.g.:

```
20251223_120000_S1_CDSE_GDAL/
├── extract/                 # SAFE unzip (GDAL pipeline)
├── cog/                     # downloaded VV/VH COGs (COG pipeline)
└── dist/
    ├── VV_clip.tif
    └── VH_clip.tif
```

(Exact folder names depend on pipeline selection.)

---

## ⚠️ Notes & Gotchas

- EPSG:4326 uses **degrees**; do not force `xRes=10` expecting 10 meters.
- GDAL pipelines depend on **GCPs** inside the measurement TIFF / COG.
- Pixel values may differ between “raw” and “clipped” stats because clipping changes the sampled region and warp resampling can affect local values.

---

## 📜 License

MIT
