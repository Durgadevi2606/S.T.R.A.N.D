"""
S.T.R.A.N.D — Copernicus Data Space Ecosystem (CDSE) API Client

Handles OAuth2 authentication, product catalog queries, and file downloads
for Sentinel-1 GRD, Sentinel-2 L2A, and Copernicus DEM-30.

Key design decisions:
- Uses httpx for async-capable HTTP with connection pooling.
- Implements exponential backoff retry (max 3 attempts) per hackathon robustness requirement.
- Enforces same-orbit-track matching for SAR pre/post pairs to avoid false backscatter anomalies.
- Token auto-refresh when expiry is within 60 seconds.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from strand.config import get_settings

logger = logging.getLogger(__name__)

# Token refresh buffer — refresh 60s before expiry
TOKEN_REFRESH_BUFFER_S = 60

# Maximum retries for API calls
MAX_RETRIES = 3

# Backoff base (seconds): 2s, 4s, 8s
BACKOFF_BASE_S = 2


class CDSEAuthError(Exception):
    """Raised when CDSE authentication fails."""


class CDSECatalogError(Exception):
    """Raised when CDSE catalog query fails."""


class CDSEDownloadError(Exception):
    """Raised when CDSE product download fails."""


class CDSEClient:
    """
    Client for the Copernicus Data Space Ecosystem (CDSE) APIs.

    Manages OAuth2 token lifecycle, product discovery, and downloads.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client_id = settings.cdse.client_id
        self._client_secret = settings.cdse.client_secret
        self._auth_url = settings.cdse.auth_url
        self._odata_url = settings.cdse.odata_url
        self._download_url = settings.cdse.download_url

        self._access_token: str | None = None
        self._token_expiry: float = 0.0

        self._http = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()

    # ─── Authentication ──────────────────────────────────────

    def _ensure_token(self) -> str:
        """
        Ensure a valid OAuth2 access token is available.

        Refreshes the token if it's expired or about to expire.
        Uses client_credentials grant type (machine-to-machine).

        Returns:
            Valid access token string.

        Raises:
            CDSEAuthError: If token acquisition fails after retries.
        """
        if (
            self._access_token is not None
            and time.time() < self._token_expiry - TOKEN_REFRESH_BUFFER_S
        ):
            return self._access_token

        logger.info("Acquiring CDSE OAuth2 token...")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._http.post(
                    self._auth_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                data = response.json()

                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 600)
                self._token_expiry = time.time() + expires_in

                logger.info(
                    "CDSE token acquired (expires in %ds)", expires_in
                )
                return self._access_token

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "CDSE auth attempt %d/%d failed: %s",
                    attempt, MAX_RETRIES, e.response.status_code,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_S ** attempt)
            except httpx.RequestError as e:
                logger.warning(
                    "CDSE auth attempt %d/%d network error: %s",
                    attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_S ** attempt)

        raise CDSEAuthError(
            f"Failed to acquire CDSE token after {MAX_RETRIES} attempts"
        )

    @property
    def _auth_headers(self) -> dict[str, str]:
        """Get authorization headers with a valid token."""
        token = self._ensure_token()
        return {"Authorization": f"Bearer {token}"}

    # ─── Catalog Queries ─────────────────────────────────────

    def search_sentinel1_grd(
        self,
        bbox: list[float],
        start_date: date,
        end_date: date,
        orbit_direction: str | None = None,
        relative_orbit_number: int | None = None,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Search for Sentinel-1 GRD products in the CDSE catalog.

        Args:
            bbox: Bounding box as [west, south, east, north] in WGS84.
            start_date: Start of the search window.
            end_date: End of the search window.
            orbit_direction: 'ASCENDING' or 'DESCENDING' (optional).
            relative_orbit_number: Filter by specific orbit track (critical for
                                   pre/post comparison accuracy).
            max_results: Maximum number of products to return.

        Returns:
            List of product metadata dictionaries.

        Raises:
            CDSECatalogError: If the catalog query fails.
        """
        west, south, east, north = bbox
        footprint = (
            f"OData.CSC.Intersects(area=geography'SRID=4326;POLYGON(("
            f"{west} {south},{east} {south},{east} {north},"
            f"{west} {north},{west} {south}))')"
        )

        filters = [
            f"Collection/Name eq 'SENTINEL-1'",
            f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            f"and att/OData.CSC.StringAttribute/Value eq 'GRD')",
            f"ContentDate/Start ge {start_date.isoformat()}T00:00:00.000Z",
            f"ContentDate/Start le {end_date.isoformat()}T23:59:59.999Z",
            footprint,
        ]

        if orbit_direction:
            filters.append(
                f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'orbitDirection' "
                f"and att/OData.CSC.StringAttribute/Value eq '{orbit_direction}')"
            )

        if relative_orbit_number is not None:
            filters.append(
                f"Attributes/OData.CSC.IntegerAttribute/any(att:att/Name eq 'relativeOrbitNumber' "
                f"and att/OData.CSC.IntegerAttribute/Value eq {relative_orbit_number})"
            )

        filter_str = " and ".join(filters)
        params = {
            "$filter": filter_str,
            "$top": max_results,
            "$orderby": "ContentDate/Start desc",
        }

        return self._query_catalog(params)

    def search_sentinel2_l2a(
        self,
        bbox: list[float],
        start_date: date,
        end_date: date,
        max_cloud_pct: float = 50.0,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Search for Sentinel-2 L2A products with cloud cover filtering.

        Args:
            bbox: Bounding box as [west, south, east, north].
            start_date: Start of search window.
            end_date: End of search window.
            max_cloud_pct: Maximum cloud cover percentage.
            max_results: Maximum products to return.

        Returns:
            List of product metadata dicts, sorted by cloud cover ascending.
        """
        west, south, east, north = bbox
        footprint = (
            f"OData.CSC.Intersects(area=geography'SRID=4326;POLYGON(("
            f"{west} {south},{east} {south},{east} {north},"
            f"{west} {north},{west} {south}))')"
        )

        filters = [
            "Collection/Name eq 'SENTINEL-2'",
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'S2MSI2A')",
            f"ContentDate/Start ge {start_date.isoformat()}T00:00:00.000Z",
            f"ContentDate/Start le {end_date.isoformat()}T23:59:59.999Z",
            f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' "
            f"and att/OData.CSC.DoubleAttribute/Value le {max_cloud_pct})",
            footprint,
        ]

        filter_str = " and ".join(filters)
        params = {
            "$filter": filter_str,
            "$top": max_results,
            "$orderby": "Attributes/OData.CSC.DoubleAttribute/Value asc",
        }

        return self._query_catalog(params)

    def find_sar_pair(
        self,
        bbox: list[float],
        disaster_date: date,
        pre_window_days: int = 24,
        post_window_days: int = 24,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """
        Find a matching pre/post disaster SAR pair from the SAME orbital track.

        This is critical: comparing images from different orbit tracks introduces
        false backscatter anomalies due to different incidence angles. The hackathon
        rules explicitly require same-track comparison.

        Algorithm:
        1. Search for post-disaster images within post_window_days.
        2. For each post image, extract its relative orbit number.
        3. Search for pre-disaster images with the SAME relative orbit number.
        4. Select the closest temporal match (ideally 12 days apart = one revisit cycle).

        Args:
            bbox: AOI bounding box [west, south, east, north].
            disaster_date: Date of the disaster event.
            pre_window_days: Days before disaster to search for pre-event image.
            post_window_days: Days after disaster to search for post-event image.

        Returns:
            Tuple of (pre_product, post_product) dicts, or (None, None) if no match.
        """
        logger.info(
            "Searching for SAR pair around %s (pre: %d days, post: %d days)",
            disaster_date, pre_window_days, post_window_days,
        )

        # Step 1: Find post-disaster images
        post_start = disaster_date + timedelta(days=1)
        post_end = disaster_date + timedelta(days=post_window_days)
        post_products = self.search_sentinel1_grd(
            bbox=bbox,
            start_date=post_start,
            end_date=post_end,
        )

        if not post_products:
            logger.warning("No post-disaster SAR products found in window %s to %s", post_start, post_end)
            return None, None

        logger.info("Found %d post-disaster SAR candidates", len(post_products))

        # Step 2: For each post product, find matching pre-product on same orbit
        for post_prod in post_products:
            # Extract relative orbit number from product attributes
            rel_orbit = self._extract_attribute(
                post_prod, "relativeOrbitNumber", attr_type="integer"
            )
            if rel_orbit is None:
                logger.warning(
                    "Post product %s missing relativeOrbitNumber, skipping",
                    post_prod.get("Name", "unknown"),
                )
                continue

            orbit_dir = self._extract_attribute(
                post_prod, "orbitDirection", attr_type="string"
            )

            logger.info(
                "Post candidate: %s (orbit %d, %s)",
                post_prod.get("Name", "?"), rel_orbit, orbit_dir,
            )

            # Step 3: Search for pre-disaster image on same orbit track
            pre_end = disaster_date
            pre_start = disaster_date - timedelta(days=pre_window_days)

            pre_products = self.search_sentinel1_grd(
                bbox=bbox,
                start_date=pre_start,
                end_date=pre_end,
                orbit_direction=orbit_dir,
                relative_orbit_number=int(rel_orbit),
            )

            if pre_products:
                pre_prod = pre_products[0]  # Most recent pre-disaster on same orbit
                logger.info(
                    "SAR pair found! Pre: %s, Post: %s (orbit %d, %s)",
                    pre_prod.get("Name", "?"),
                    post_prod.get("Name", "?"),
                    rel_orbit,
                    orbit_dir,
                )
                return pre_prod, post_prod

        logger.warning("No matching SAR pair found with same orbital track")
        return None, None

    def _query_catalog(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute an OData catalog query with retry logic."""
        url = f"{self._odata_url}/Products"

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._http.get(
                    url, params=params, headers=self._auth_headers
                )
                response.raise_for_status()
                data = response.json()
                products = data.get("value", [])
                logger.info("Catalog query returned %d products", len(products))
                return products

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "Catalog query attempt %d/%d failed: HTTP %s",
                    attempt, MAX_RETRIES, e.response.status_code,
                )
                if e.response.status_code == 401:
                    # Token expired — force refresh
                    self._access_token = None
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_S ** attempt)
            except httpx.RequestError as e:
                logger.warning(
                    "Catalog query attempt %d/%d network error: %s",
                    attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_S ** attempt)

        raise CDSECatalogError(f"Catalog query failed after {MAX_RETRIES} attempts")

    # ─── Product Downloads ───────────────────────────────────

    def download_product(
        self,
        product_id: str,
        output_dir: str | Path,
        product_name: str | None = None,
    ) -> Path:
        """
        Download a product from CDSE by its ID.

        Streams the download to disk with progress logging.
        Implements retry with exponential backoff.

        Args:
            product_id: The CDSE product UUID.
            output_dir: Directory to save the downloaded file.
            product_name: Optional filename (defaults to product_id.zip).

        Returns:
            Path to the downloaded file.

        Raises:
            CDSEDownloadError: If download fails after retries.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = product_name or f"{product_id}.zip"
        output_path = output_dir / filename

        if output_path.exists():
            logger.info("Product already downloaded: %s", output_path)
            return output_path

        url = f"{self._download_url}/Products({product_id})/$value"

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "Downloading product %s (attempt %d/%d)...",
                    product_id, attempt, MAX_RETRIES,
                )

                with self._http.stream(
                    "GET", url, headers=self._auth_headers
                ) as response:
                    response.raise_for_status()

                    total_size = int(response.headers.get("content-length", 0))
                    downloaded = 0

                    with open(output_path, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=8192):
                            f.write(chunk)
                            downloaded += len(chunk)

                    logger.info(
                        "Downloaded %s (%.1f MB)",
                        filename, downloaded / 1e6,
                    )
                    return output_path

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "Download attempt %d/%d failed: HTTP %s",
                    attempt, MAX_RETRIES, e.response.status_code,
                )
                if e.response.status_code == 401:
                    self._access_token = None
                # Clean up partial download
                if output_path.exists():
                    output_path.unlink()
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_S ** attempt)

            except httpx.RequestError as e:
                logger.warning(
                    "Download attempt %d/%d network error: %s",
                    attempt, MAX_RETRIES, e,
                )
                if output_path.exists():
                    output_path.unlink()
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_S ** attempt)

        raise CDSEDownloadError(
            f"Failed to download product {product_id} after {MAX_RETRIES} attempts"
        )

    # ─── DEM Download ────────────────────────────────────────

    def download_dem30(
        self,
        bbox: list[float],
        output_dir: str | Path,
    ) -> list[Path]:
        """
        Download Copernicus DEM-30 tiles covering the given bounding box.

        DEM tiles are distributed as 1°×1° tiles. This method determines
        which tiles are needed and downloads each one.

        Args:
            bbox: Bounding box as [west, south, east, north].
            output_dir: Directory to save DEM tiles.

        Returns:
            List of paths to downloaded DEM tiles.
        """
        import math

        west, south, east, north = bbox
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Determine required 1°×1° tiles
        lon_min = math.floor(west)
        lon_max = math.ceil(east)
        lat_min = math.floor(south)
        lat_max = math.ceil(north)

        downloaded_tiles: list[Path] = []

        for lat in range(lat_min, lat_max):
            for lon in range(lon_min, lon_max):
                # DEM tile naming convention
                lat_prefix = "N" if lat >= 0 else "S"
                lon_prefix = "E" if lon >= 0 else "W"
                tile_name = (
                    f"Copernicus_DSM_COG_10_{lat_prefix}{abs(lat):02d}_00_"
                    f"{lon_prefix}{abs(lon):03d}_00_DEM"
                )

                tile_path = output_dir / f"{tile_name}.tif"

                if tile_path.exists():
                    logger.info("DEM tile already exists: %s", tile_name)
                    downloaded_tiles.append(tile_path)
                    continue

                # Search for DEM tile in CDSE catalog
                try:
                    products = self._query_catalog({
                        "$filter": (
                            f"Collection/Name eq 'COP-DEM' and "
                            f"contains(Name, '{tile_name}')"
                        ),
                        "$top": 1,
                    })

                    if products:
                        product_id = products[0]["Id"]
                        path = self.download_product(
                            product_id, output_dir, f"{tile_name}.tif"
                        )
                        downloaded_tiles.append(path)
                    else:
                        logger.warning("DEM tile not found in catalog: %s", tile_name)

                except (CDSECatalogError, CDSEDownloadError) as e:
                    logger.error("Failed to download DEM tile %s: %s", tile_name, e)

        logger.info("Downloaded %d DEM tiles", len(downloaded_tiles))
        return downloaded_tiles

    # ─── Utility Methods ─────────────────────────────────────

    @staticmethod
    def _extract_attribute(
        product: dict[str, Any],
        attr_name: str,
        attr_type: str = "string",
    ) -> Any:
        """
        Extract a typed attribute from a CDSE product metadata dict.

        CDSE OData returns attributes in a polymorphic structure:
        Attributes/OData.CSC.StringAttribute or IntegerAttribute etc.

        Args:
            product: Product metadata dict from catalog query.
            attr_name: Attribute name to extract.
            attr_type: Expected type ('string', 'integer', 'double').

        Returns:
            The attribute value, or None if not found.
        """
        attributes = product.get("Attributes", [])
        for attr in attributes:
            if attr.get("Name") == attr_name:
                return attr.get("Value")
        return None

    @staticmethod
    def extract_sensing_date(product: dict[str, Any]) -> date | None:
        """Extract the sensing start date from a CDSE product."""
        content_date = product.get("ContentDate", {})
        start_str = content_date.get("Start")
        if start_str:
            return datetime.fromisoformat(start_str.rstrip("Z")).date()
        return None
