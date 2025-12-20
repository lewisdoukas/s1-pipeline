# Sentinel-1 ASF → pyroSAR RTC → RGB Pipeline

End-to-end Python pipeline for **downloading Sentinel-1 GRD data from ASF**, processing it locally with **SNAP / pyroSAR** into **RTC-like georeferenced VV & VH**, clipping to a given AOI, and generating a **SAR RGB composite** suitable for data fusion and GeoAI workflows.

---

## 🚀 Features

- 🔍 Search Sentinel-1 **GRD HD (IW, VV+VH)** scenes via **ASF**
- 📦 Download original **SAFE ZIP**
- 🛰️ Local **RTC-style processing** using **SNAP (via pyroSAR)**
- ✂️ AOI subsetting **during processing** (fast & disk-efficient)
- 🌍 Output in **EPSG:4326 or UTM**
- 🎨 Generate **SAR RGB** composite (VV / VH / VV−VH)
- ⏱️ Built-in runtime measurement

---

## 📁 Output Structure

```
<timestamp>_S1_ASF_pyroSAR/
├── aoi.geojson
├── <SAFE>.zip
├── rtc_out/
│   ├── *_VV*.tif
│   └── *_VH*.tif
└── dist/
    ├── VV_clip.tif
    ├── VH_clip.tif
    └── S1_RGB.tif
```

---

## 🧠 Processing Logic (High Level)

1. **ASF search** (Sentinel-1 GRD HD, IW, VV+VH)
2. **SAFE ZIP download**
3. **pyroSAR geocode**

   - Calibration
   - Thermal & border noise removal
   - Orbit application
   - Terrain flattening
   - Terrain correction
   - AOI subsetting

4. **Clipping** (safety check)
5. **RGB generation**

   - R = VV (dB)
   - G = VH (dB)
   - B = VV − VH (dB)

---

## 🧰 Requirements

### System

- macOS / Linux
- ≥ 20 GB free disk space (less if AOI is small)
- SNAP installed

### SNAP

Install ESA SNAP and ensure `gpt` exists:

```
/Applications/esa-snap/bin/gpt
```

### Python

Tested with Python **3.10**

---

## 📦 Python Dependencies

```bash
pip3 install -r requirements.txt
```

> **Important:** `pyroSAR` requires GDAL (`osgeo`) bindings compatible with your system GDAL.

---

## 🔑 Credentials

Create a `config.py` file:

```python
EARTHDATA_USERNAME = "your_earthdata_username"
EARTHDATA_PASSWORD = "your_earthdata_password"
```

---

## ▶️ How to Run

```bash
python3 asf_pyrosar.py
```

The script will:

- search ASF
- download the most recent scene in the date range
- process it
- generate clipped VV, VH and RGB outputs

---

## 🗺️ Configuration Parameters

Inside `__main__`:

```python
bbox4326 = [minLon, minLat, maxLon, maxLat]

date_start = "YYYY-MM-DD"
date_end   = "YYYY-MM-DD"

target_crs = 4326      # WGS84
# target_crs = 32634   # UTM Zone 34N
```

---

## ⏱️ Runtime Expectations

With AOI subsetting enabled:

| Step          | Typical Time |
| ------------- | ------------ |
| ASF search    | < 1 s        |
| SAFE download | 1–5 min      |
| pyroSAR RTC   | 3–15 min     |
| RGB creation  | < 10 s       |

Without subsetting, full-scene RTC may take **1+ hour** and >10 GB temp space.

---

## 🧪 Notes & Gotchas

- Orbit warnings (RESORB vs POEORB) are **normal**
- AOI subsetting is **strongly recommended**
- Use **UTM** for best fusion with Sentinel-2

---

## 🔄 Future Extensions

- Batch processing (multiple scenes)
- Sentinel-1 + Sentinel-2 fusion
- GeoAI model ingestion

---

## 📜 License

MIT

---

## 🙌 Acknowledgements

- ESA SNAP
- ASF DAAC
- pyroSAR developers

---
