import os, time, zipfile, glob, datetime
import rasterio
from pystac_client import Client
import boto3
from botocore.config import Config

from helpers import cdse_download_safe_zip, cdse_get_access_token, cdse_odata_find_s1_grdh_product, stac_find_latest_s1_grd_item, warp_gcps_clip
from config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY



# ----------------------------- #
# ----------- MAIN ------------ #
# ----------------------------- #
def cog_gdal(bbox4326, date_start, date_end, workdir):
    print("*** Start COG -> GDAL pipeline...")

    t0 = time.perf_counter()

    datetime_range = f"{date_start}/{date_end}"

    os.makedirs(workdir, exist_ok=True)

    # -----------------------------
    # 1) STAC SEARCH + DOWNLOAD SAFE ZIP
    # -----------------------------
    print("1) STAC search...")
    ENDPOINT = "https://eodata.dataspace.copernicus.eu"
    catalog = Client.open("https://catalogue.dataspace.copernicus.eu/stac")

    search = catalog.search(
        collections= ["sentinel-1-grd"],
        datetime= datetime_range,
        bbox= bbox4326,
    )

    items = list(search.items())

    # Download the latest vv & vh
    item = items[0]
    print("   STAC item:", item.id, "datetime:", item.datetime)

    s3_vv_url = item.assets["vv"].href
    s3_vh_url = item.assets["vh"].href


    bucket = "eodata"
    key_vv = s3_vv_url.replace("s3://eodata/", "")
    key_vh = s3_vh_url.replace("s3://eodata/", "")

    s3 = boto3.client(
        "s3",
        endpoint_url= ENDPOINT,
        aws_access_key_id= AWS_ACCESS_KEY_ID,
        aws_secret_access_key= AWS_SECRET_ACCESS_KEY,
        config=Config(signature_version= "s3v4"),
    )


    cog_dir = os.path.join(workdir, "cog")
    os.makedirs(cog_dir, exist_ok=True)

    vv_tif = os.path.join(cog_dir, "VV.tif")
    vh_tif = os.path.join(cog_dir, "VH.tif")

    print("2) Download COG TIFFs...")
    s3.download_file(bucket, key_vv, vv_tif)
    s3.download_file(bucket, key_vh, vh_tif)

    print("RAW VV COG:", vv_tif)
    print("RAW VH COG:", vh_tif)


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

    print("\nCOG-GDAL DONE. Outputs in:", dist_dir)

    t1 = time.perf_counter()
    print(f"Total Sentinel-1 pipeline time: {(t1 - t0)/60:.2f} minutes")



if __name__ == "__main__":
    bbox4326 = [21.650108363494013, 40.66771202000291, 21.748606076871027, 40.7560964624422]

    date_start = "2025-12-01"
    date_end   = "2025-12-15"

    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    workdir = now + "_S1_COG_GDAL"

    cog_gdal(bbox4326, date_start, date_end, workdir)
