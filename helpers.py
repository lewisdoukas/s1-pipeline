import os, re, json, glob, time
from datetime import datetime, timedelta, timezone
import urllib.parse
import requests
import numpy as np
import rasterio
from rasterio.mask import mask
from shapely.geometry import box, mapping
from shapely.ops import transform as shp_transform
from pyproj import Transformer
from pystac_client import Client
from osgeo import gdal



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


def bbox4326_to_odata_polygon(bbox):
    minx, miny, maxx, maxy = bbox
    # OData expects lon lat and a closed polygon
    return (
        f"geography'SRID=4326;POLYGON(("
        f"{minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}"
        f"))'"
    )


def to_db(x):
    # If data is already in dB skip this
    # dB is when: np.nanmin(vv), np.nanmax(vv) gives -35 -> +5
    return 10.0 * np.log10(np.maximum(x, 1e-10))

def stretch01(x, pmin=2, pmax=98):
    lo, hi = np.nanpercentile(x, [pmin, pmax])
    y = (x - lo) / (hi - lo + 1e-12)
    return np.clip(y, 0, 1).astype(np.float32)


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


# ---------------------------------------------- # 
# --------------- CDSE Related ----------------- #
# ---------------------------------------------- # 
def parse_s1_times_from_name(name_or_id):
    """
    Extract sensing start/end from Sentinel-1 name pattern:
    ..._YYYYMMDDThhmmss_YYYYMMDDThhmmss_...
    """
    m = re.search(r"_(\d{8}T\d{6})_(\d{8}T\d{6})_", name_or_id)
    if not m:
        raise ValueError(f"Could not parse sensing times from: {name_or_id}")
    t0 = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    t1 = datetime.strptime(m.group(2), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    return t0, t1


def stac_find_latest_s1_grd_item(bbox4326, datetime_range, stac_url=None):
    """
    Returns the latest STAC item for Sentinel-1 GRD within bbox/time.
    """
    stac_url = stac_url or "https://stac.dataspace.copernicus.eu/v1/"

    catalog = Client.open(stac_url)

    search = catalog.search(
        collections=["sentinel-1-grd"],
        datetime=datetime_range,
        bbox=list(bbox4326),
    )

    items = list(search.items())
    if not items:
        raise RuntimeError("No STAC items found for the given bbox/date range.")

    items.sort(key=lambda it: it.datetime or datetime.min, reverse=True)
    return items[0]


def cdse_odata_find_s1_grdh_product(bbox4326, stac_item_id, top=10):
    """
    Find the matching Sentinel-1 GRD IW product in OData even when the last 4-char suffix differs.
    Uses: Collection + contains(Name,'IW_GRDH') + AOI + ContentDate window. :contentReference[oaicite:2]{index=2}
    """
    t0, t1 = parse_s1_times_from_name(stac_item_id)

    t_start = (t0 - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    t_end   = (t0 + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    poly = bbox4326_to_odata_polygon(bbox4326)

    filter_expr = (
        "Collection/Name eq 'SENTINEL-1' "
        "and contains(Name,'IW_GRDH') "
        "and (endswith(Name,'.SAFE') or endswith(Name,'.safe')) "
        "and not contains(Name,'_COG') "
        f"and OData.CSC.Intersects(area={poly}) "
        f"and ContentDate/Start ge {t_start} and ContentDate/Start le {t_end}"
    )

    params = {
        "$filter": filter_expr,
        "$select": "Id,Name,ContentDate,PublicationDate",
        "$orderby": "PublicationDate desc",
        "$top": str(top),
    }

    url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products?" + urllib.parse.urlencode(params)

    j = requests.get(url, timeout=60).json()
    vals = j.get("value", [])
    if not vals:
        raise RuntimeError("OData returned no products for AOI + sensing time window.")

    # Build a stable prefix from the STAC id by removing the last _XXXX and optional _COG
    prefix = re.sub(r"_[0-9A-F]{4}(_COG)?$", "", stac_item_id)

    # Prefer candidates starting with the same prefix (but different last 4 chars)
    best = None
    for v in vals:
        if v["Name"].startswith(prefix):
            best = v
            break
    best = best or vals[0]

    return best["Id"], best["Name"]


def derive_safe_name_from_stac_item(item):
    """
    Try to derive SAFE product name from STAC item.
    Often item.id ends with _COG; SAFE is typically without _COG.
    """
    item_id = item.id
    safe_base = item_id[:-4] if item_id.endswith("_COG") else item_id

    return safe_base


def cdse_get_access_token(username, password):
    token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    data = {
        "client_id": "cdse-public",
        "grant_type": "password",
        "username": username,
        "password": password,
    }
    r = requests.post(token_url, data=data, timeout=60)
    r.raise_for_status()
    return r.json()["access_token"]


def cdse_find_product_id_by_name(name):
    """
    Query CDSE OData Products for a product Id by exact Name.
    Endpoint family is described in CDSE Catalogue/OData docs. :contentReference[oaicite:4]{index=4}
    """
    odata_base = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
    filter_expr = f"Collection/Name eq 'SENTINEL-1' and Name eq '{name}'"
    url = odata_base + "?" + urllib.parse.urlencode({"$filter": filter_expr})
    j = requests.get(url, timeout=60).json()
    vals = j.get("value", [])
    if not vals:
        return None
    return vals[0]["Id"], vals[0]["Name"]


def cdse_download_safe_zip(product_id, out_zip, access_token):
    headers = {"Authorization": f"Bearer {access_token}"}

    # CDSE support example uses zipper.dataspace.../Products(<ID>)/$value :contentReference[oaicite:5]{index=5}
    url = f"https://zipper.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"

    with requests.get(url, headers=headers, stream=True, timeout=(30, 600)) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        got = 0
        with open(out_zip, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                got += len(chunk)
                if total:
                    print(f"\rDownloading SAFE: {100*got/total:6.2f}% ({got/1e6:.1f}/{total/1e6:.1f} MB)", end="")
    print("\nSaved:", out_zip)
    return out_zip


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