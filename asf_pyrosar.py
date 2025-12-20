import os
os.environ["PATH"] = "/Applications/esa-snap/bin:" + os.environ.get("PATH", "")

import time, glob, json, datetime
import numpy as np

import asf_search as asf
import rasterio
from rasterio.mask import mask
from shapely.geometry import box, mapping
from shapely.ops import transform as shp_transform
from pyproj import Transformer

from pyroSAR import identify
from pyroSAR.snap.util import geocode

from config import EARTHDATA_USERNAME, EARTHDATA_PASSWORD



# ----------------------------- #
# ---------- HELPERS ---------- #
# ----------------------------- #
def write_aoi_geojson_from_bbox(bbox4326, out_geojson="aoi.geojson"):
    geom = mapping(box(*bbox4326))
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": geom}
        ],
    }
    with open(out_geojson, "w") as f:
        json.dump(fc, f)
    return out_geojson


def to_db(x):
    # If data is already in dB skip this
    # dB is when: np.nanmin(vv), np.nanmax(vv) gives -35 -> +5
    return 10.0 * np.log10(np.maximum(x, 1e-10))

def stretch01(x, pmin=2, pmax=98):
    lo, hi = np.nanpercentile(x, [pmin, pmax])
    y = (x - lo) / (hi - lo + 1e-12)
    return np.clip(y, 0, 1).astype(np.float32)


def build_sar_rgb(vv_db, vh_db):
    # False-color SAR composite
    # R = VV(dB), G = VH(dB), B = VV-VH(dB)
    ratio = vv_db - vh_db
    R = stretch01(vv_db)
    G = stretch01(vh_db)
    B = stretch01(ratio)
    return np.dstack([R, G, B]).astype(np.float32)


def clip_to_bbox4326(in_path, out_path, bbox4326):
    with rasterio.open(in_path) as src:
        if src.crs is None:
            raise ValueError(f"{in_path} has no CRS; cannot clip.")

        geom4326 = box(*bbox4326)
        transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        geom_src = shp_transform(transformer.transform, geom4326)

        out_img, out_transform = mask(src, [mapping(geom_src)], crop=True)

        meta = src.meta.copy()
        meta.update(
            height=out_img.shape[1],
            width=out_img.shape[2],
            transform=out_transform,
        )

    with rasterio.open(out_path, "w", **meta) as dst:
        dst.write(out_img)

    return out_path


def write_rgb_geotiff(rgb_float01, ref_profile, out_path):
    rgb_u8 = (rgb_float01 * 255).round().astype(np.uint8)  # HxWx3
    profile = ref_profile.copy()
    profile.update(count=3, dtype=rasterio.uint8, nodata=None)

    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(np.transpose(rgb_u8, (2, 0, 1)))

    return out_path



# ----------------------------- #
# ---------- M A I N ---------- #
# ----------------------------- #
def main(bbox4326, date_start, date_end, target_crs, workdir):
    t0 = time.perf_counter()

    os.makedirs(workdir, exist_ok=True)

    # -----------------------------
    # 1) ASF SEARCH + DOWNLOAD SAFE ZIP
    # -----------------------------
    print("1) Authenticating to ASF (Earthdata)...")
    session = asf.ASFSession().auth_with_creds(EARTHDATA_USERNAME, EARTHDATA_PASSWORD)

    aoi_wkt = box(*bbox4326).wkt

    print("2) Searching Sentinel-1 GRD_HD IW VV+VH...")
    results = asf.search(
        platform="Sentinel-1",
        processingLevel="GRD_HD",  # ensures GRD High-res, Dual-pol scenes
        beamMode="IW",
        polarization="VV+VH",
        start=date_start,
        end=date_end,
        intersectsWith=aoi_wkt,
    )

    if not results:
        raise RuntimeError("No ASF scenes found for bbox/date criteria.")

    # Sort by start time descending
    results = sorted(results, key=lambda r: r.properties.get("startTime", ""), reverse=True)
    scene = results[0]

    scene_name = scene.properties["sceneName"]
    print("Selected scene:", scene_name)

    print("3) Downloading SAFE zip...")
    # ASF download produces a .zip
    scene.download(path=workdir, session=session)

    # Find the downloaded file
    zips = glob.glob(os.path.join(workdir, f"{scene_name}*.zip"))
    if not zips:
        zips = glob.glob(os.path.join(workdir, "*.zip"))
    if not zips:
        raise RuntimeError(f"SAFE zip not found in {workdir} after download.")
    safe_zip = zips[0]
    print("Saved SAFE zip:", safe_zip)


    print("4) Create geojson based on bbox...")
    aoi_path = write_aoi_geojson_from_bbox(bbox4326, os.path.join(workdir, "aoi.geojson"))
    print("AOI saved:", aoi_path)


    # -----------------------------
    # 2) pyroSAR RTC / geocode -> VV/VH GeoTIFFs
    # -----------------------------
    print("5) Running pyroSAR geocode (RTC/georeference) ...")
    rtc_dir = os.path.join(workdir, "rtc_out")
    os.makedirs(rtc_dir, exist_ok=True)

    scene_obj = identify(safe_zip)

    geocode(
        infile=scene_obj,
        outdir=rtc_dir,
        t_srs=target_crs,
        spacing=10,
        polarizations=["VV", "VH"],
        scaling="dB",
        geocoding_type="Range-Doppler",
        removeS1BorderNoise=True,
        removeS1ThermalNoise=True,
        terrainFlattening=True,
        demName="Copernicus 30m Global DEM",
        cleanup=True,
        shapefile=aoi_path,
    )

    vv_paths = glob.glob(os.path.join(rtc_dir, "**", "*VV*.tif"), recursive=True)
    vh_paths = glob.glob(os.path.join(rtc_dir, "**", "*VH*.tif"), recursive=True)
    if not vv_paths or not vh_paths:
        raise RuntimeError("Could not find VV/VH GeoTIFFs produced by pyroSAR. Check SNAP logs.")

    vv_tif = vv_paths[0]
    vh_tif = vh_paths[0]
    print("RTC VV:", vv_tif)
    print("RTC VH:", vh_tif)


    # -----------------------------
    # 3) Clip VV/VH to bbox4326
    # -----------------------------
    print("6) Clipping VV/VH to bbox4326 ...")
    dist_dir = os.path.join(workdir, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    vv_clip = os.path.join(dist_dir, "VV_clip.tif")
    vh_clip = os.path.join(dist_dir, "VH_clip.tif")

    clip_to_bbox4326(vv_tif, vv_clip, bbox4326)
    clip_to_bbox4326(vh_tif, vh_clip, bbox4326)

    # Verify alignment
    with rasterio.open(vv_clip) as a, rasterio.open(vh_clip) as b:
        if a.crs != b.crs or a.transform != b.transform or a.width != b.width or a.height != b.height:
            raise RuntimeError("Clipped VV and VH are not perfectly aligned. Use a shared-window clip if needed.")

    print("VV clipped:", vv_clip)
    print("VH clipped:", vh_clip)


    # -----------------------------
    # 4) Build RGB
    # -----------------------------
    print("7) Building RGB (R=VV, G=VH, B=VV-VH) and saving GeoTIFF...")
    with rasterio.open(vv_clip) as vv_src, rasterio.open(vh_clip) as vh_src:
        vv_db = vv_src.read(1).astype(np.float32)
        vh_db = vh_src.read(1).astype(np.float32)

        if vv_src.nodata is not None:
            vv_db = np.where(vv_db == vv_src.nodata, np.nan, vv_db)
        if vh_src.nodata is not None:
            vh_db = np.where(vh_db == vh_src.nodata, np.nan, vh_db)

        rgb = build_sar_rgb(vv_db, vh_db)

        rgb_path = os.path.join(dist_dir, "S1_RGB.tif")
        write_rgb_geotiff(rgb, vv_src.profile, rgb_path)

    print("RGB saved:", rgb_path)
    print("\nDONE. Outputs in:", dist_dir)

    t1 = time.perf_counter()
    print(f"Total Sentinel-1 pipeline time: {(t1 - t0)/60:.2f} minutes")



if __name__ == "__main__":
    bbox4326 = [21.650108363494013, 40.66771202000291, 21.748606076871027, 40.7560964624422]

    date_start = "2025-12-01"
    date_end   = "2025-12-15"
    # target_crs = 32634 #UTM Zone 34N
    target_crs = 4326

    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    workdir = now + "_S1_ASF_pyroSAR"

    main(bbox4326, date_start, date_end, target_crs, workdir)

