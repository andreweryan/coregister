import os
import cv2
import subprocess
import numpy as np
import geopandas as gpd
from PIL import Image
from osgeo import gdal
import geopandas as gpd
from affine import Affine
from datetime import datetime
from shapely.geometry import Point
from typing import List, Tuple, Union, Optional

gdal.UseExceptions()

Image.MAX_IMAGE_PIXELS = None

def pixel2longlat(
    geotransform: Union[str, List[float]], px: float, py: float
) -> Tuple[float, float]:
    """Convert Column, Row pixel coordinates to Longitude, Latitude coordinates.

    Args:
        geotransform (List): Image GDAL GeoTransform
        px (float): Column pixel coordinate
        py (float): Row pixel coordinate

    Return:
        Tuple(float, float): Longitude, Latitude coordinates
    """
    if isinstance(geotransform, str):
        affine_transform = Affine.from_gdal(*eval(str(geotransform)))
    else:
        affine_transform = Affine.from_gdal(*geotransform)

    x, y = affine_transform * (px, py)

    return (x, y)


def coregister(target_image_path: str, reference_image_path: str, algorithm: str = "orb", limit_keypoints: Optional[int] = 10, aoi_path: Optional[str] = None, gcp_path: Optional[str] = None):
    start = datetime.now()

    if algorithm == "orb":
        orb = cv2.ORB_create()
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

        print("Loading Target Image")
        target_array = np.array(Image.open(target_image_path))
        print("Getting keypoints, descriptors for target image")
        target_keypoints, target_descriptors = orb.detectAndCompute(target_array, None)
        target_array = None
        print(f"Number of target keypoints: {len(target_keypoints)}")

        print("Loading Reference Image")
        reference_array = np.array(Image.open(reference_image_path))
        print("Getting keypoints, descriptors for reference image")
        reference_keypoints, reference_descriptors = orb.detectAndCompute(reference_array, None)
        reference_array = None
        print(f"Number of reference keypoints keypoints: {len(reference_keypoints)}")
    elif algorithm == "sift":
        print("SIFT is memory intensive on large images, use with caution as you may run out of memory.\n")
        sift = cv2.SIFT_create()
        bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=True)
        print("Loading Target Image")
        target_array = np.array(Image.open(target_image_path))
        print("Getting keypoints, descriptors for target image")
        target_keypoints, target_descriptors = sift.detectAndCompute(target_array, None)
        target_array = None
        print(f"Number of target keypoints: {len(target_keypoints)}")

        print("Loading Reference Image")
        reference_array = np.array(Image.open(reference_image_path))
        print("Getting keypoints, descriptors for reference image")
        reference_keypoints, reference_descriptors = sift.detectAndCompute(reference_array, None)
        reference_array = None
        print(f"Number of reference keypoints keypoints: {len(reference_keypoints)}")
    

    print("Getting matching keypoints")
    matches = bf.match(reference_descriptors, target_descriptors)
    matches = sorted(matches, key=lambda x: x.distance)
    print(f"Number of matching keypoints: {len(matches)}")

    reference_geo_points = list()

    if limit_keypoints:
        reference_px_points = [(reference_keypoints[match.queryIdx].pt[0], reference_keypoints[match.queryIdx].pt[1]) for match in matches][0:limit_keypoints]
        target_px_points = [(target_keypoints[match.trainIdx].pt[0], target_keypoints[match.trainIdx].pt[1]) for match in matches][0:limit_keypoints]
    else:
        reference_px_points = [(reference_keypoints[match.queryIdx].pt[0], reference_keypoints[match.queryIdx].pt[1]) for match in matches]
        target_px_points = [(target_keypoints[match.trainIdx].pt[0], target_keypoints[match.trainIdx].pt[1]) for match in matches]
    
    reference_image = gdal.Open(reference_image_path)

    reference_geo_points = list()
    reference_geotransform = reference_image.GetGeoTransform()
    print("Converting keypoints to Long, Lat coordinates")
    for i in range(len(reference_px_points)):
        x, y = pixel2longlat(reference_geotransform, reference_px_points[i][0], reference_px_points[i][1])
        reference_geo_points.append((x, y))

    gcps = list()

    print("Converting keypoints to GCPs")

    if aoi_path:
        print("Restricting GCPs to specified AOI file")
    
    valid_gcps = []
    
    for i in range(len(reference_geo_points)):
        point = Point(reference_geo_points[i][0], reference_geo_points[i][1])
        if aoi_path:
            aoi = gpd.read_file(aoi_path)
            if aoi.contains(point).any():
                valid_gcps.append(point)
                gcp = f"-gcp {target_px_points[i][0]} {target_px_points[i][1]} {reference_geo_points[i][0]} {reference_geo_points[i][1]}"
                gcps.append(gcp)
        else:
            valid_gcps.append(point)
            gcp = f"-gcp {target_px_points[i][0]} {target_px_points[i][1]} {reference_geo_points[i][0]} {reference_geo_points[i][1]}"
            gcps.append(gcp)
    
    gdf = gpd.GeoDataFrame(valid_gcps, columns=["geometry"])
    gdf = gdf.set_crs(crs="EPSG:4326")

    if gcp_path:
        gdf.to_file(gcp_path, index=False)

    gcp_string = " ".join(gcps)

    if len(valid_gcps) < 5:
        print(f"Not enough GCP found, exiting...")
        pass
    else:
        translate = f"gdal_translate -of COG -a_srs EPSG:4326 -co COMPRESS=JPEG {gcp_string} {target_image_path} {target_image_path.split('.')[0]}_{algorithm}_registered.tif"

        print("Coregistering images")
        subprocess.run(translate, shell=True)

    end = datetime.now()
    print(f"Time to reregister: {end - start}")

image_paths = [
    "/Users/andrewryan/projects/data/coregister/imagery/103001009D218E00_clipped2.tif",
    "/Users/andrewryan/projects/data/coregister/imagery/103001009BC75100_clipped2.tif"
    ]
target_image_path = image_paths[0]
reference_image_path =  image_paths[1]

# target_image_path = "/Users/andrewryan/projects/data/coregister/imagery/103001009D218E00_clipped.tif"
# reference_image_path = "/Users/andrewryan/projects/data/coregister/imagery/103001009BC75100_clipped.tif"
algorithm = "orb"
aoi_path = "/Users/andrewryan/projects/data/coregister/aoi.geojson"
gcp_path = f"/Users/andrewryan/projects/data/coregister/gcps_{algorithm}.geojson"
coregister(target_image_path, reference_image_path, algorithm=algorithm, limit_keypoints=5, aoi_path=None, gcp_path=gcp_path)