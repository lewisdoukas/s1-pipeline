import os, time, zipfile, glob, datetime
import rasterio
from osgeo import gdal

from helpers import cdse_download_safe_zip, cdse_get_access_token, cdse_odata_find_s1_grdh_product, stac_find_latest_s1_grd_item
from config import CDSE_USERNAME, CDSE_PASSWORD



def warp_gcps_clip(src_tif, dst_tif, bbox4326):
    minlon, minlat, maxlon, maxlat = bbox4326

    opts = gdal.WarpOptions(
        tps=True,                 # use GCPs
        srcSRS="EPSG:4326",       # interpret GCP lon/lat
        dstSRS="EPSG:4326",       # keep output in 4326

        outputBounds=(minlon, minlat, maxlon, maxlat),
        outputBoundsSRS="EPSG:4326",

        resampleAlg="bilinear",       
        srcNodata=0,
        dstNodata=0,
        outputType=gdal.GDT_UInt16,

        multithread=True,
        warpOptions=["NUM_THREADS=ALL_CPUS"],
        creationOptions=[
            "TILED=YES",
            "COMPRESS=ZSTD",
            "BIGTIFF=IF_SAFER",
        ],
    )

    out = gdal.Warp(dst_tif, src_tif, options=opts)
    if out is None:
        raise RuntimeError(f"GDAL warp failed for {src_tif}")
    out.FlushCache()
    out = None


# ----------------------------- #
# ----------- MAIN ------------ #
# ----------------------------- #
def cdse_gdal(bbox4326, date_start, date_end, workdir):
    print("*** Start CDSE -> GDAL pipeline...")

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

    # -----------------------------
    # 2) GDAL turn SAFE.zip into VV/VH clipped GeoTIFFs
    # -----------------------------
    print("3) GDAL -> GeoTIFF VV/VH...")
    extract_dir = os.path.join(workdir, "extract")
    os.makedirs(extract_dir, exist_ok=True)

    safe_name = os.path.basename(safe_zip).replace(".zip", "")
    safe_dir = os.path.join(extract_dir, safe_name)

    if not os.path.exists(safe_dir):
        with zipfile.ZipFile(safe_zip, "r") as z:
            z.extractall(extract_dir)

    meas_dir = os.path.join(safe_dir, "measurement")

    vv_files = glob.glob(os.path.join(meas_dir, "*-vv-*.tiff"))
    vh_files = glob.glob(os.path.join(meas_dir, "*-vh-*.tiff"))

    if not vv_files or not vh_files:
        raise RuntimeError("VV or VH measurement TIFF not found in SAFE")

    vv_tif = vv_files[0]
    vh_tif = vh_files[0]
    print("RAW VV:", vv_tif)
    print("RAW VH:", vh_tif)

    # -----------------------------
    # 3) Clip VV/VH to bbox4326
    # -----------------------------
    print("4) Clipping VV/VH to bbox4326 ...")
    dist_dir = os.path.join(workdir, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    vv_clip = os.path.join(dist_dir, "VV_clip.tif")
    vh_clip = os.path.join(dist_dir, "VH_clip.tif")

    warp_gcps_clip(vv_tif, vv_clip, bbox4326)
    warp_gcps_clip(vh_tif, vh_clip, bbox4326)


    # Verify alignment
    with rasterio.open(vv_clip) as a, rasterio.open(vh_clip) as b:
        if a.crs != b.crs or a.transform != b.transform or a.width != b.width or a.height != b.height:
            raise RuntimeError("Clipped VV and VH are not perfectly aligned. Use a shared-window clip if needed.")

    print("VV clipped:", vv_clip)
    print("VH clipped:", vh_clip)

    print("\nCDSE-GDAL DONE. Outputs in:", dist_dir)

    t1 = time.perf_counter()
    print(f"Total Sentinel-1 pipeline time: {(t1 - t0)/60:.2f} minutes")



if __name__ == "__main__":
    bbox4326 = [21.650108363494013, 40.66771202000291, 21.748606076871027, 40.7560964624422]

    date_start = "2025-12-01"
    date_end   = "2025-12-15"

    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    workdir = now + "_S1_CDSE_GDAL"

    cdse_gdal(bbox4326, date_start, date_end, workdir)
