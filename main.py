import datetime
from cdse_gdal import cdse_gdal
from asf_pyrosar import asf_pyrosar
from cdse_pyrosar import cdse_pyrosar


def main(bbox4326, date_start, date_end, target_crs, pipeline):
    if pipeline not in ["GDAL", "ASF", "CDSE"]:
        raise ValueError(f"Invalid pipeline name.")
    
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    workdir = now + "_S1_CDSE_pyroSAR"
    
    if pipeline == "GDAL":
        workdir = now + "_S1_CDSE_GDAL"
        cdse_gdal(bbox4326, date_start, date_end, workdir)
        return
    elif pipeline == "ASF":
        workdir = now + "_S1_ASF_pyroSAR"
        asf_pyrosar(bbox4326, date_start, date_end, target_crs, workdir)
        return
    
    cdse_pyrosar(bbox4326, date_start, date_end, target_crs, workdir)



if __name__ == "__main__":
    bbox4326 = [21.650108363494013, 40.66771202000291, 21.748606076871027, 40.7560964624422]

    date_start = "2025-12-01"
    date_end   = "2025-12-15"
    # target_crs = 32634 #UTM Zone 34N
    target_crs = 4326

    # pipeline in ["GDAL", "ASF", "CDSE"]
    pipeline = "GDAL"

    main(bbox4326, date_start, date_end, target_crs, pipeline)
