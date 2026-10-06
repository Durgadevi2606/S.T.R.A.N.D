"""
S.T.R.A.N.D — Test Configuration & Shared Fixtures

Provides reusable test fixtures for all modules:
- Synthetic SAR arrays, flood masks, DEM data
- GeoDataFrame factories for roads, bridges, buildings, settlements
- In-memory DuckDB database with schema
- Temporary file directories
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from shapely.geometry import LineString, Point, Polygon, box


# ─── Environment Override ────────────────────────────────────
# Prevent real API calls during tests

os.environ.setdefault("CDSE_CLIENT_ID", "test-client-id")
os.environ.setdefault("CDSE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("STRAND_API_KEYS", "test-api-key")
os.environ.setdefault("STRAND_DATABASE_PATH", ":memory:")


# ─── Constants ───────────────────────────────────────────────

UTM_EPSG = 32645  # Nepal UTM Zone 45N
UTM_CRS = CRS.from_epsg(UTM_EPSG)
WGS84_CRS = CRS.from_epsg(4326)

# AOI around Bhote Koshi valley (UTM coordinates, ~10km × 10km)
AOI_WEST_UTM = 400000.0
AOI_SOUTH_UTM = 3080000.0
AOI_EAST_UTM = 410000.0
AOI_NORTH_UTM = 3090000.0
PIXEL_SIZE = 10.0  # meters

# Array dimensions for test data
ARRAY_WIDTH = int((AOI_EAST_UTM - AOI_WEST_UTM) / PIXEL_SIZE)  # 1000
ARRAY_HEIGHT = int((AOI_NORTH_UTM - AOI_SOUTH_UTM) / PIXEL_SIZE)  # 1000


# ─── Raster Fixtures ────────────────────────────────────────

@pytest.fixture
def transform():
    """Affine transform for test rasters (UTM 10m)."""
    return from_bounds(
        AOI_WEST_UTM, AOI_SOUTH_UTM, AOI_EAST_UTM, AOI_NORTH_UTM,
        ARRAY_WIDTH, ARRAY_HEIGHT,
    )


@pytest.fixture
def small_transform():
    """Smaller 100x100 transform for fast tests."""
    return from_bounds(
        AOI_WEST_UTM, AOI_SOUTH_UTM, AOI_WEST_UTM + 1000, AOI_SOUTH_UTM + 1000,
        100, 100,
    )


@pytest.fixture
def pre_event_sigma0():
    """Synthetic pre-event σ⁰ array (stable backscatter)."""
    rng = np.random.default_rng(42)
    # Typical land backscatter: mean ~0.05 (σ⁰ linear)
    return rng.exponential(scale=0.05, size=(100, 100)).astype(np.float32)


@pytest.fixture
def post_event_sigma0(pre_event_sigma0):
    """
    Synthetic post-event σ⁰ with a flood region.

    Top-left quadrant has reduced backscatter (water = specular reflection).
    """
    post = pre_event_sigma0.copy()
    # Create flood zone in top-left quadrant (rows 10-50, cols 10-50)
    post[10:50, 10:50] *= 0.05  # 20× reduction → strong flood signal
    return post


@pytest.fixture
def dem_array():
    """Synthetic DEM array: gradient from 1000m (south) to 4000m (north)."""
    elevation = np.linspace(1000, 4000, 100).reshape(-1, 1)
    elevation = np.tile(elevation, (1, 100)).astype(np.float32)
    # Add some noise
    rng = np.random.default_rng(42)
    elevation += rng.normal(0, 50, elevation.shape).astype(np.float32)
    return elevation


@pytest.fixture
def flood_mask():
    """Binary flood mask: top-left 40×40 region is flooded."""
    mask = np.zeros((100, 100), dtype=bool)
    mask[10:50, 10:50] = True
    return mask


@pytest.fixture
def confidence_array(flood_mask):
    """Confidence array aligned with flood mask."""
    conf = np.zeros((100, 100), dtype=np.float32)
    conf[flood_mask] = 0.85
    return conf


@pytest.fixture
def tmp_dir():
    """Temporary directory for test outputs, cleaned up after test."""
    with tempfile.TemporaryDirectory(prefix="strand_test_") as d:
        yield Path(d)


@pytest.fixture
def sample_geotiff(tmp_dir, pre_event_sigma0, small_transform):
    """Write a sample GeoTIFF and return its path."""
    path = tmp_dir / "sample.tif"
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": 100,
        "height": 100,
        "count": 1,
        "crs": UTM_CRS,
        "transform": small_transform,
    }
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(pre_event_sigma0, 1)
    return path


@pytest.fixture
def sample_dem_geotiff(tmp_dir, dem_array, small_transform):
    """Write a sample DEM GeoTIFF and return its path."""
    path = tmp_dir / "dem.tif"
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": 100,
        "height": 100,
        "count": 1,
        "crs": UTM_CRS,
        "transform": small_transform,
    }
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(dem_array, 1)
    return path


# ─── GeoDataFrame Fixtures ──────────────────────────────────

@pytest.fixture
def roads_gdf():
    """GeoDataFrame of 5 road segments across the test area."""
    roads = [
        {
            "id": f"road-{i}", "osm_id": f"osm-road-{i}",
            "highway": "primary" if i < 2 else "secondary",
            "name": f"Road {i}",
            "geometry": LineString([
                (AOI_WEST_UTM + i * 200, AOI_SOUTH_UTM + 500),
                (AOI_WEST_UTM + i * 200 + 800, AOI_SOUTH_UTM + 500),
            ]),
        }
        for i in range(5)
    ]
    gdf = gpd.GeoDataFrame(roads, crs=UTM_CRS)
    gdf["length_m"] = gdf.geometry.length
    return gdf


@pytest.fixture
def bridges_gdf():
    """GeoDataFrame of 3 bridge points."""
    bridges = [
        {
            "id": f"bridge-{i}", "osm_id": f"osm-bridge-{i}",
            "name": f"Bridge {i}",
            "geometry": Point(AOI_WEST_UTM + 500 + i * 300, AOI_SOUTH_UTM + 500),
        }
        for i in range(3)
    ]
    return gpd.GeoDataFrame(bridges, crs=UTM_CRS)


@pytest.fixture
def buildings_gdf():
    """GeoDataFrame of 10 building polygons (20m × 20m each)."""
    buildings = []
    for i in range(10):
        x = AOI_WEST_UTM + 100 + (i % 5) * 200
        y = AOI_SOUTH_UTM + 100 + (i // 5) * 200
        buildings.append({
            "id": f"building-{i}", "osm_id": f"osm-bldg-{i}",
            "building": "residential",
            "geometry": box(x, y, x + 20, y + 20),
        })
    return gpd.GeoDataFrame(buildings, crs=UTM_CRS)


@pytest.fixture
def settlements_gdf():
    """GeoDataFrame of 4 settlement points."""
    settlements = [
        {"id": "s1", "name": "Barhabise", "place": "town",
         "estimated_population": 200,
         "geometry": Point(AOI_WEST_UTM + 200, AOI_SOUTH_UTM + 200)},
        {"id": "s2", "name": "Tatopani", "place": "village",
         "estimated_population": 80,
         "geometry": Point(AOI_WEST_UTM + 800, AOI_SOUTH_UTM + 800)},
        {"id": "s3", "name": "Kodari", "place": "village",
         "estimated_population": 50,
         "geometry": Point(AOI_WEST_UTM + 500, AOI_SOUTH_UTM + 500)},
        {"id": "s4", "name": "Liping", "place": "hamlet",
         "estimated_population": 30,
         "geometry": Point(AOI_WEST_UTM + 900, AOI_SOUTH_UTM + 100)},
    ]
    return gpd.GeoDataFrame(settlements, crs=UTM_CRS)


@pytest.fixture
def flood_gdf():
    """GeoDataFrame with a single flood polygon."""
    flood_poly = box(
        AOI_WEST_UTM + 100, AOI_SOUTH_UTM + 100,
        AOI_WEST_UTM + 500, AOI_SOUTH_UTM + 500,
    )
    return gpd.GeoDataFrame(
        [{"id": "flood-1", "area_m2": flood_poly.area, "geometry": flood_poly}],
        crs=UTM_CRS,
    )


@pytest.fixture
def healthcare_gdf():
    """GeoDataFrame of 2 healthcare facilities (hub nodes)."""
    hubs = [
        {"id": "h1", "name": "Barhabise Hospital", "amenity": "hospital",
         "geometry": Point(AOI_WEST_UTM + 100, AOI_SOUTH_UTM + 900)},
        {"id": "h2", "name": "Tatopani Clinic", "amenity": "clinic",
         "geometry": Point(AOI_WEST_UTM + 900, AOI_SOUTH_UTM + 900)},
    ]
    return gpd.GeoDataFrame(hubs, crs=UTM_CRS)


# ─── Database Fixtures ──────────────────────────────────────

@pytest.fixture
def analysis_id():
    """A fixed analysis ID for tests."""
    return "test-analysis-00000001"


@pytest.fixture
def db_connection():
    """In-memory DuckDB connection with schema applied."""
    import duckdb

    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL spatial; LOAD spatial;")

    # Run a minimal schema creation
    from strand.db.migrations import SCHEMA_SQL
    for statement in SCHEMA_SQL.split(";"):
        stmt = statement.strip()
        if stmt and not stmt.startswith("--"):
            try:
                conn.execute(stmt)
            except Exception:
                pass  # Skip if table already exists

    yield conn
    conn.close()
