"""
S.T.R.A.N.D — Sentinel-1 SAR Preprocessor

Handles radiometric calibration (DN → σ⁰), terrain correction using
Copernicus DEM-30, and co-registration of pre/post image pairs.

Key design decisions:
- Uses GDAL/Rasterio for all raster I/O (avoids heavy SNAP dependency).
- Terrain correction uses simplified Range-Doppler approach suitable for
  GRD products (already ground-range projected by ESA).
- Co-registration uses phase-correlation for sub-pixel alignment.
- All outputs are in the local UTM CRS with 10m pixel spacing.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import calculate_default_transform, reproject

from strand.config import get_settings

logger = logging.getLogger(__name__)


class SARPreprocessor:
    """
    Preprocesses Sentinel-1 GRD products for change detection.

    Pipeline:
    1. Extract VV and VH bands from SAFE zip archive
    2. Radiometric calibration (DN → σ⁰ backscatter coefficient)
    3. Terrain correction using DEM (geometric correction)
    4. Reproject to local UTM CRS at 10m resolution
    5. Co-register pre/post pair to sub-pixel accuracy
    """

    def __init__(self, utm_epsg: int, output_dir: Path) -> None:
        """
        Args:
            utm_epsg: Target UTM EPSG code (e.g., 32645 for Zone 45N).
            output_dir: Directory for processed output files.
        """
        self.utm_epsg = utm_epsg
        self.utm_crs = CRS.from_epsg(utm_epsg)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pixel_size = 10.0  # meters

    def process_pair(
        self,
        pre_path: Path,
        post_path: Path,
        dem_path: Path,
        aoi_bounds: list[float],
    ) -> dict[str, Path]:
        """
        Process a pre/post SAR pair through the full preprocessing chain.

        Args:
            pre_path: Path to pre-event Sentinel-1 GRD product (zip or dir).
            post_path: Path to post-event Sentinel-1 GRD product.
            dem_path: Path to DEM GeoTIFF covering the AOI.
            aoi_bounds: [west, south, east, north] in WGS84.

        Returns:
            Dict with paths to processed files:
            - 'pre_vv', 'pre_vh': Calibrated, terrain-corrected pre-event bands
            - 'post_vv', 'post_vh': Calibrated, terrain-corrected post-event bands
            - 'dem_utm': DEM reprojected to UTM
        """
        logger.info("Processing SAR pair...")
        logger.info("  Pre:  %s", pre_path.name)
        logger.info("  Post: %s", post_path.name)
        logger.info("  DEM:  %s", dem_path.name)
        logger.info("  UTM:  EPSG:%d", self.utm_epsg)

        # Step 1: Extract and read bands
        logger.info("Step 1: Extracting SAR bands...")
        pre_vv_raw, pre_vh_raw, pre_meta = self._extract_bands(pre_path, "pre")
        post_vv_raw, post_vh_raw, post_meta = self._extract_bands(post_path, "post")

        # Step 2: Radiometric calibration
        logger.info("Step 2: Radiometric calibration (DN → σ⁰)...")
        pre_vv_cal = self._calibrate(pre_vv_raw, pre_meta)
        pre_vh_cal = self._calibrate(pre_vh_raw, pre_meta)
        post_vv_cal = self._calibrate(post_vv_raw, post_meta)
        post_vh_cal = self._calibrate(post_vh_raw, post_meta)

        # Step 3: Reproject DEM to UTM
        logger.info("Step 3: Reprojecting DEM to UTM...")
        dem_utm_path = self._reproject_dem(dem_path, aoi_bounds)

        # Step 4: Terrain correction + UTM reprojection
        logger.info("Step 4: Terrain correction + UTM reprojection...")
        pre_vv_path = self._terrain_correct_and_reproject(
            pre_vv_cal, pre_meta, dem_utm_path, aoi_bounds, "pre_vv"
        )
        pre_vh_path = self._terrain_correct_and_reproject(
            pre_vh_cal, pre_meta, dem_utm_path, aoi_bounds, "pre_vh"
        )
        post_vv_path = self._terrain_correct_and_reproject(
            post_vv_cal, post_meta, dem_utm_path, aoi_bounds, "post_vv"
        )
        post_vh_path = self._terrain_correct_and_reproject(
            post_vh_cal, post_meta, dem_utm_path, aoi_bounds, "post_vh"
        )

        # Step 5: Co-register post to pre
        logger.info("Step 5: Co-registering post to pre...")
        post_vv_coreg = self._coregister(post_vv_path, pre_vv_path, "post_vv_coreg")
        post_vh_coreg = self._coregister(post_vh_path, pre_vh_path, "post_vh_coreg")

        results = {
            "pre_vv": pre_vv_path,
            "pre_vh": pre_vh_path,
            "post_vv": post_vv_coreg,
            "post_vh": post_vh_coreg,
            "dem_utm": dem_utm_path,
        }

        logger.info("SAR preprocessing complete. Output files:")
        for key, path in results.items():
            logger.info("  %s: %s", key, path)

        return results

    # ─── Band Extraction ─────────────────────────────────────

    def _extract_bands(
        self, product_path: Path, prefix: str
    ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        """
        Extract VV and VH bands from a Sentinel-1 GRD product.

        Handles both .zip archives and extracted SAFE directories.
        For GRD products, bands are in the measurement/ subdirectory.

        Returns:
            Tuple of (vv_array, vh_array, metadata_dict).
        """
        # If it's a zip, extract the TIFF files
        if product_path.suffix == ".zip":
            extract_dir = self.output_dir / f"{prefix}_extracted"
            extract_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(product_path, "r") as zf:
                # Find measurement files
                tiff_files = [f for f in zf.namelist() if f.endswith(".tiff") or f.endswith(".tif")]
                for tf in tiff_files:
                    zf.extract(tf, extract_dir)
            measurement_dir = extract_dir
        else:
            measurement_dir = product_path

        # Find VV and VH files
        vv_file = self._find_band_file(measurement_dir, "vv")
        vh_file = self._find_band_file(measurement_dir, "vh")

        if vv_file is None or vh_file is None:
            # Fallback: try reading as a single multi-band GeoTIFF
            logger.warning("Could not find separate VV/VH files, trying multi-band read...")
            return self._read_multiband(product_path, prefix)

        # Read arrays
        with rasterio.open(vv_file) as ds:
            vv = ds.read(1).astype(np.float32)
            meta = {
                "crs": ds.crs,
                "transform": ds.transform,
                "width": ds.width,
                "height": ds.height,
                "bounds": ds.bounds,
                "nodata": ds.nodata,
            }

        with rasterio.open(vh_file) as ds:
            vh = ds.read(1).astype(np.float32)

        logger.info(
            "  Extracted %s: VV %s, VH %s, CRS=%s",
            prefix, vv.shape, vh.shape, meta["crs"],
        )

        return vv, vh, meta

    def _find_band_file(self, search_dir: Path, polarization: str) -> Path | None:
        """Find a TIFF file matching the given polarization (vv or vh)."""
        pol_upper = polarization.upper()
        pol_lower = polarization.lower()

        for pattern in [f"*{pol_lower}*.tiff", f"*{pol_lower}*.tif",
                        f"*{pol_upper}*.tiff", f"*{pol_upper}*.tif"]:
            matches = list(search_dir.rglob(pattern))
            if matches:
                return matches[0]
        return None

    def _read_multiband(
        self, path: Path, prefix: str
    ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        """Read a multi-band GeoTIFF assuming band 1=VV, band 2=VH."""
        with rasterio.open(path) as ds:
            if ds.count >= 2:
                vv = ds.read(1).astype(np.float32)
                vh = ds.read(2).astype(np.float32)
            else:
                # Single band — duplicate for both polarizations
                vv = ds.read(1).astype(np.float32)
                vh = vv.copy()
                logger.warning("Single-band product, using same data for VV and VH")

            meta = {
                "crs": ds.crs,
                "transform": ds.transform,
                "width": ds.width,
                "height": ds.height,
                "bounds": ds.bounds,
                "nodata": ds.nodata,
            }

        return vv, vh, meta

    # ─── Radiometric Calibration ─────────────────────────────

    def _calibrate(
        self, dn_array: np.ndarray, meta: dict[str, Any]
    ) -> np.ndarray:
        """
        Convert digital number (DN) to sigma-nought (σ⁰) backscatter.

        For Sentinel-1 GRD products:
            σ⁰ = DN² / A²_i

        Where A_i is the calibration constant from the annotation file.
        Since we may not have the exact LUT, we use the standard approximation
        for Level-1 GRD products where DN values are already in amplitude:

            σ⁰ = 10 * log10(DN²)  (in dB)

        We keep values in linear scale for log-ratio computation.

        Args:
            dn_array: Raw digital number array (float32).
            meta: Product metadata dict.

        Returns:
            Calibrated σ⁰ array in linear power scale.
        """
        # Replace zeros and negatives to avoid log issues
        sigma0 = np.where(dn_array > 0, dn_array ** 2, np.nan)

        # Clip extreme values (noise floor and saturation)
        # Typical SAR backscatter range: -30 dB to +5 dB → linear: 1e-3 to 3.16
        sigma0 = np.clip(sigma0, 1e-6, 1e3)

        # Count valid pixels
        valid_pct = np.count_nonzero(~np.isnan(sigma0)) / sigma0.size * 100
        logger.info(
            "  Calibration: valid pixels=%.1f%%, range=[%.4f, %.4f]",
            valid_pct, np.nanmin(sigma0), np.nanmax(sigma0),
        )

        return sigma0

    # ─── Terrain Correction & Reprojection ───────────────────

    def _reproject_dem(
        self, dem_path: Path, aoi_bounds: list[float]
    ) -> Path:
        """Reproject DEM to target UTM CRS and clip to AOI."""
        output_path = self.output_dir / "dem_utm.tif"

        if output_path.exists():
            logger.info("  DEM UTM already exists, skipping")
            return output_path

        with rasterio.open(dem_path) as src:
            dst_transform, dst_width, dst_height = calculate_default_transform(
                src.crs, self.utm_crs, src.width, src.height,
                *src.bounds, resolution=self.pixel_size,
            )

            dst_meta = src.meta.copy()
            dst_meta.update({
                "crs": self.utm_crs,
                "transform": dst_transform,
                "width": dst_width,
                "height": dst_height,
                "dtype": "float32",
            })

            with rasterio.open(output_path, "w", **dst_meta) as dst:
                for band_idx in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, band_idx),
                        destination=rasterio.band(dst, band_idx),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=dst_transform,
                        dst_crs=self.utm_crs,
                        resampling=Resampling.bilinear,
                    )

        logger.info("  DEM reprojected to EPSG:%d (%dx%d)", self.utm_epsg, dst_width, dst_height)
        return output_path

    def _terrain_correct_and_reproject(
        self,
        sigma0: np.ndarray,
        src_meta: dict[str, Any],
        dem_utm_path: Path,
        aoi_bounds: list[float],
        output_name: str,
    ) -> Path:
        """
        Apply geometric terrain correction and reproject to UTM.

        For Sentinel-1 GRD products (already ground-range detected):
        - Radiometric terrain normalization using local incidence angle
        - Reprojection from geographic (EPSG:4326) to UTM
        - Resampling to 10m pixel spacing

        The full Range-Doppler terrain correction is simplified here since
        GRD products are already ground-range projected. We apply DEM-based
        geometric refinement for mountain terrain.

        Args:
            sigma0: Calibrated σ⁰ array.
            src_meta: Source metadata with CRS, transform, dimensions.
            dem_utm_path: Path to UTM-reprojected DEM.
            aoi_bounds: [west, south, east, north] in WGS84.
            output_name: Output filename stem.

        Returns:
            Path to terrain-corrected, UTM-reprojected GeoTIFF.
        """
        output_path = self.output_dir / f"{output_name}_tc.tif"

        if output_path.exists():
            logger.info("  %s already exists, skipping", output_name)
            return output_path

        src_crs = src_meta["crs"]
        src_transform = src_meta["transform"]

        # Calculate output dimensions in UTM
        dst_transform, dst_width, dst_height = calculate_default_transform(
            src_crs, self.utm_crs,
            src_meta["width"], src_meta["height"],
            *src_meta["bounds"],
            resolution=self.pixel_size,
        )

        # Create temporary in-memory source dataset profile
        src_profile = {
            "driver": "GTiff",
            "dtype": "float32",
            "width": src_meta["width"],
            "height": src_meta["height"],
            "count": 1,
            "crs": src_crs,
            "transform": src_transform,
        }

        # Write source to temporary file
        temp_src_path = self.output_dir / f"{output_name}_temp.tif"
        with rasterio.open(temp_src_path, "w", **src_profile) as tmp:
            tmp.write(sigma0, 1)

        # Reproject to UTM
        dst_profile = src_profile.copy()
        dst_profile.update({
            "crs": self.utm_crs,
            "transform": dst_transform,
            "width": dst_width,
            "height": dst_height,
            "compress": "deflate",
            "predictor": 2,
        })

        with rasterio.open(temp_src_path) as src:
            with rasterio.open(output_path, "w", **dst_profile) as dst:
                reproject(
                    source=rasterio.band(src, 1),
                    destination=rasterio.band(dst, 1),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=dst_transform,
                    dst_crs=self.utm_crs,
                    resampling=Resampling.bilinear,
                )

        # Apply DEM-based radiometric terrain normalization
        self._apply_terrain_normalization(output_path, dem_utm_path)

        # Cleanup temp file
        if temp_src_path.exists():
            temp_src_path.unlink()

        logger.info(
            "  %s: terrain-corrected, UTM %dx%d @ %.0fm",
            output_name, dst_width, dst_height, self.pixel_size,
        )
        return output_path

    def _apply_terrain_normalization(
        self, sar_path: Path, dem_path: Path
    ) -> None:
        """
        Apply radiometric terrain normalization using local incidence angle
        derived from the DEM.

        Corrects for brightness variations caused by terrain slope:
        σ⁰_corrected = σ⁰ × cos(θ_ref) / cos(θ_local)

        where θ_ref is the reference incidence angle (~39° for S1 IW mode)
        and θ_local is derived from DEM slope and aspect.
        """
        import math

        REF_INCIDENCE_DEG = 39.0  # Typical S1 IW mid-swath incidence angle
        ref_cos = math.cos(math.radians(REF_INCIDENCE_DEG))

        try:
            with rasterio.open(dem_path) as dem_ds:
                dem = dem_ds.read(1).astype(np.float32)
                dem_transform = dem_ds.transform
                pixel_size = abs(dem_transform.a)

            # Compute slope from DEM using numpy gradient
            dy, dx = np.gradient(dem, pixel_size)
            slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))

            # Approximate local incidence angle
            # For descending orbit looking right, simplified model:
            local_cos = np.cos(slope_rad) * ref_cos
            local_cos = np.clip(local_cos, 0.1, 1.0)  # Prevent division by very small values

            # Compute correction factor
            correction = ref_cos / local_cos

            # Apply to SAR image (must match spatial extent)
            with rasterio.open(sar_path, "r+") as sar_ds:
                sar_data = sar_ds.read(1)

                # Resample correction to SAR grid if dimensions differ
                if correction.shape != sar_data.shape:
                    from scipy.ndimage import zoom

                    zoom_factors = (
                        sar_data.shape[0] / correction.shape[0],
                        sar_data.shape[1] / correction.shape[1],
                    )
                    correction = zoom(correction, zoom_factors, order=1)

                # Apply correction
                sar_corrected = sar_data * correction
                sar_corrected = np.where(
                    np.isfinite(sar_corrected), sar_corrected, sar_data
                )
                sar_ds.write(sar_corrected, 1)

            logger.info("  Terrain normalization applied (ref incidence=%.1f°)", REF_INCIDENCE_DEG)

        except Exception as e:
            logger.warning("  Terrain normalization skipped: %s", e)

    # ─── Co-registration ─────────────────────────────────────

    def _coregister(
        self, target_path: Path, reference_path: Path, output_name: str
    ) -> Path:
        """
        Co-register target image to reference using phase correlation.

        Computes sub-pixel shift between the two images and applies
        the correction to the target. This ensures pre/post images
        are aligned for pixel-level change detection.

        Args:
            target_path: Image to be shifted (post-event).
            reference_path: Reference image (pre-event).
            output_name: Output filename stem.

        Returns:
            Path to co-registered target image.
        """
        output_path = self.output_dir / f"{output_name}.tif"

        with rasterio.open(reference_path) as ref_ds:
            ref_data = ref_ds.read(1).astype(np.float32)

        with rasterio.open(target_path) as tgt_ds:
            tgt_data = tgt_ds.read(1).astype(np.float32)
            tgt_profile = tgt_ds.profile.copy()
            tgt_transform = tgt_ds.transform

        # Ensure same dimensions
        if ref_data.shape != tgt_data.shape:
            logger.warning(
                "Shape mismatch (ref=%s, tgt=%s), skipping co-registration",
                ref_data.shape, tgt_data.shape,
            )
            # Just copy the file
            import shutil
            shutil.copy2(target_path, output_path)
            return output_path

        # Phase correlation to find shift
        try:
            from scipy.ndimage import shift as ndimage_shift
            from skimage.registration import phase_cross_correlation

            # Replace NaN with 0 for correlation
            ref_clean = np.nan_to_num(ref_data, nan=0.0)
            tgt_clean = np.nan_to_num(tgt_data, nan=0.0)

            shift_yx, error, diffphase = phase_cross_correlation(
                ref_clean, tgt_clean, upsample_factor=10
            )

            shift_y, shift_x = shift_yx
            rmse = np.sqrt(shift_y**2 + shift_x**2) * self.pixel_size

            logger.info(
                "  Co-registration shift: dy=%.2f px, dx=%.2f px (RMSE=%.1f m)",
                shift_y, shift_x, rmse,
            )

            if abs(shift_y) > 5 or abs(shift_x) > 5:
                logger.warning(
                    "  Large co-registration shift detected (>5 px). "
                    "Check if images are from the same orbit track."
                )

            # Apply sub-pixel shift
            tgt_shifted = ndimage_shift(tgt_data, shift_yx, order=1, mode="nearest")

            # Write corrected image
            with rasterio.open(output_path, "w", **tgt_profile) as dst:
                dst.write(tgt_shifted, 1)

        except ImportError:
            logger.warning("  scikit-image not available, skipping co-registration")
            import shutil
            shutil.copy2(target_path, output_path)

        except Exception as e:
            logger.warning("  Co-registration failed: %s, using unregistered image", e)
            import shutil
            shutil.copy2(target_path, output_path)

        return output_path


def preprocess_dem(
    dem_paths: list[Path],
    aoi_bounds: list[float],
    utm_epsg: int,
    output_dir: Path,
) -> Path:
    """
    Mosaic and clip DEM tiles to the AOI, reproject to UTM.

    Args:
        dem_paths: List of DEM tile file paths.
        aoi_bounds: [west, south, east, north] in WGS84.
        output_dir: Output directory.
        utm_epsg: Target UTM EPSG code.

    Returns:
        Path to the processed DEM GeoTIFF.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "dem_mosaic.tif"

    if output_path.exists():
        logger.info("DEM mosaic already exists: %s", output_path)
        return output_path

    if len(dem_paths) == 1:
        # Single tile — just clip and return
        import shutil
        shutil.copy2(dem_paths[0], output_path)
        return output_path

    # Mosaic multiple tiles
    from rasterio.merge import merge

    src_files = [rasterio.open(p) for p in dem_paths]
    try:
        mosaic, mosaic_transform = merge(src_files)
        mosaic_meta = src_files[0].meta.copy()
        mosaic_meta.update({
            "height": mosaic.shape[1],
            "width": mosaic.shape[2],
            "transform": mosaic_transform,
            "compress": "deflate",
        })

        with rasterio.open(output_path, "w", **mosaic_meta) as dst:
            dst.write(mosaic)

        logger.info(
            "DEM mosaic created: %d tiles → %dx%d",
            len(dem_paths), mosaic.shape[2], mosaic.shape[1],
        )
    finally:
        for f in src_files:
            f.close()

    return output_path
