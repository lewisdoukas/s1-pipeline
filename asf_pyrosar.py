import os, time, glob, datetime
import asf_search as asf
import rasterio
from shapely.geometry import box
from pyroSAR import identify
from pyroSAR.snap.util import geocode

from helpers import clip_to_bbox4326, write_aoi_geojson_from_bbox
from config import EARTHDATA_USERNAME, EARTHDATA_PASSWORD


# ----------------------------- #
# ---------- M A I N ---------- #
# ----------------------------- #
def asf_pyrosar(bbox4326, date_start, date_end, target_crs, workdir):
    print("*** Start ASF -> pyroSAR pipeline...")

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

    print("\nASF-pyroSAR DONE. Outputs in:", dist_dir)

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

    asf_pyrosar(bbox4326, date_start, date_end, target_crs, workdir)

