import os, glob, time
from datetime import datetime
import rasterio
from pyroSAR import identify
from pyroSAR.snap.util import geocode

from helpers import cdse_download_safe_zip, cdse_get_access_token, cdse_odata_find_s1_grdh_product, clip_to_bbox4326, stac_find_latest_s1_grd_item, write_aoi_geojson_from_bbox
from config import CDSE_USERNAME, CDSE_PASSWORD



def pyrosar_rtc_geocode_safe_zip(safe_zip, rtc_dir, aoi_path, target_crs=4326, spacing=10, demName="Copernicus 30m Global DEM"):
    os.makedirs(rtc_dir, exist_ok=True)

    scene = identify(safe_zip)

    geocode(
        infile=scene,
        outdir=rtc_dir,
        t_srs=target_crs,
        spacing=spacing,
        polarizations=["VV", "VH"],
        scaling="dB",
        geocoding_type="Range-Doppler",
        removeS1BorderNoise=True,
        removeS1ThermalNoise=True,
        terrainFlattening=True,
        demName=demName,
        cleanup=True,
        shapefile=aoi_path,
    )


# ----------------------------- #
# ----------- MAIN ------------ #
# ----------------------------- #
def cdse_pyrosar(bbox4326, date_start, date_end, target_crs, workdir):
    print("*** Start CDSE -> pyroSAR pipeline...")

    t0 = time.perf_counter()

    datetime_range = f"{date_start}/{date_end}"

    os.makedirs(workdir, exist_ok=True)

    # -----------------------------
    # 1) STAC SEARCH + DOWNLOAD SAFE ZIP
    # -----------------------------
    print("1) STAC search...")
    item = stac_find_latest_s1_grd_item(bbox4326, datetime_range)
    print("   STAC item:", item.id, "datetime:", item.datetime)

    stac_id = item.id

    product_id, product_name = cdse_odata_find_s1_grdh_product(bbox4326, stac_id)

    print("Matched OData product:", product_name, "Id:", product_id)

    out_zip = os.path.join(workdir, f"{product_name}.zip")

    token = cdse_get_access_token(CDSE_USERNAME, CDSE_PASSWORD)

    print("2) Download SAFE ZIP (OData $zip)...")
    safe_zip = cdse_download_safe_zip(product_id, out_zip, token)

    print("3) Create geojson based on bbox...")
    aoi_path = write_aoi_geojson_from_bbox(bbox4326, os.path.join(workdir, "aoi.geojson"))
    print("AOI saved:", aoi_path)

    # -----------------------------
    # 2) pyroSAR RTC / geocode -> VV/VH GeoTIFFs
    # -----------------------------
    print("4) RTC/geocode with pyroSAR -> GeoTIFF VV/VH...")
    rtc_dir = os.path.join(workdir, "rtc_out")
    pyrosar_rtc_geocode_safe_zip(safe_zip, rtc_dir, aoi_path, target_crs)

    # Find VV/VH outputs produced by pyroSAR (simple glob)
    vv_paths = glob.glob(os.path.join(rtc_dir, "**", "*VV*.tif"), recursive=True)
    vh_paths = glob.glob(os.path.join(rtc_dir, "**", "*VH*.tif"), recursive=True)
    if not vv_paths or not vh_paths:
        raise RuntimeError(f"Could not find VV/VH GeoTIFFs under {rtc_dir}. Check SNAP/pyroSAR logs.")

    vv_tif = vv_paths[0]
    vh_tif = vh_paths[0]
    print("RTC VV:", vv_tif)
    print("RTC VH:", vh_tif)


    # -----------------------------
    # 3) Clip VV/VH to bbox4326
    # -----------------------------
    print("5) Clipping VV/VH to bbox4326 ...")
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

    print("\nCDSE-pyroSAR DONE. Outputs in:", dist_dir)

    t1 = time.perf_counter()
    print(f"Total Sentinel-1 pipeline time: {(t1 - t0)/60:.2f} minutes")



if __name__ == "__main__":
    bbox4326 = [21.650108363494013, 40.66771202000291, 21.748606076871027, 40.7560964624422]

    date_start = "2025-12-01"
    date_end   = "2025-12-15"
    # target_crs = 32634 #UTM Zone 34N
    target_crs = 4326

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    workdir = now + "_S1_CDSE_pyroSAR"

    cdse_pyrosar(bbox4326, date_start, date_end, target_crs, workdir)
