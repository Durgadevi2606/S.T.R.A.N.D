"""
S.T.R.A.N.D — U-Net Flood Segmentation Model

Defines the U-Net architecture for pixel-wise flood segmentation
from SAR log-ratio images. Uses segmentation-models-pytorch for
the encoder-decoder backbone.

Training data: Kuro Siwo + Sen1Floods11 datasets.
Input: 2-channel log-ratio stack (VV + VH), 256×256 tiles.
Output: Single-channel flood probability map.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

# Input tile size for inference
TILE_SIZE = 256
TILE_OVERLAP = 32


class FloodUNet(nn.Module):
    """
    U-Net model for SAR flood segmentation.

    Architecture: ResNet34 encoder + U-Net decoder.
    Input: 2-channel (VV log-ratio, VH log-ratio)
    Output: 1-channel flood probability (sigmoid activated)
    """

    def __init__(self, encoder_name: str = "resnet34", pretrained: bool = True):
        super().__init__()

        try:
            import segmentation_models_pytorch as smp

            self.model = smp.Unet(
                encoder_name=encoder_name,
                encoder_weights="imagenet" if pretrained else None,
                in_channels=2,  # VV + VH log-ratio
                classes=1,  # Binary flood/no-flood
                activation=None,  # Raw logits (apply sigmoid in forward)
            )
        except ImportError:
            logger.warning(
                "segmentation-models-pytorch not available. "
                "Using simplified built-in U-Net."
            )
            self.model = SimpleUNet(in_channels=2, out_channels=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.

        Args:
            x: Input tensor [B, 2, H, W] (VV + VH log-ratio).

        Returns:
            Flood probability tensor [B, 1, H, W] (0 to 1).
        """
        logits = self.model(x)
        return torch.sigmoid(logits)


class SimpleUNet(nn.Module):
    """Minimal U-Net fallback when segmentation-models-pytorch is unavailable."""

    def __init__(self, in_channels: int = 2, out_channels: int = 1):
        super().__init__()

        def conv_block(in_c, out_c):
            return nn.Sequential(
                nn.Conv2d(in_c, out_c, 3, padding=1),
                nn.BatchNorm2d(out_c),
                nn.ReLU(inplace=True),
                nn.Conv2d(out_c, out_c, 3, padding=1),
                nn.BatchNorm2d(out_c),
                nn.ReLU(inplace=True),
            )

        # Encoder
        self.enc1 = conv_block(in_channels, 64)
        self.enc2 = conv_block(64, 128)
        self.enc3 = conv_block(128, 256)
        self.enc4 = conv_block(256, 512)

        self.pool = nn.MaxPool2d(2)

        # Bottleneck
        self.bottleneck = conv_block(512, 1024)

        # Decoder
        self.up4 = nn.ConvTranspose2d(1024, 512, 2, stride=2)
        self.dec4 = conv_block(1024, 512)
        self.up3 = nn.ConvTranspose2d(512, 256, 2, stride=2)
        self.dec3 = conv_block(512, 256)
        self.up2 = nn.ConvTranspose2d(256, 128, 2, stride=2)
        self.dec2 = conv_block(256, 128)
        self.up1 = nn.ConvTranspose2d(128, 64, 2, stride=2)
        self.dec1 = conv_block(128, 64)

        self.final = nn.Conv2d(64, out_channels, 1)

    def forward(self, x):
        # Encoder
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))
        e4 = self.enc4(self.pool(e3))

        # Bottleneck
        b = self.bottleneck(self.pool(e4))

        # Decoder with skip connections
        d4 = self.dec4(torch.cat([self.up4(b), e4], dim=1))
        d3 = self.dec3(torch.cat([self.up3(d4), e3], dim=1))
        d2 = self.dec2(torch.cat([self.up2(d3), e2], dim=1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))

        return self.final(d1)


class FloodInference:
    """
    Tile-based inference engine for the flood segmentation model.

    Handles large rasters by splitting into overlapping tiles,
    running inference, and reassembling with blending.
    """

    def __init__(
        self,
        checkpoint_path: Path | None = None,
        device: str | None = None,
    ):
        """
        Args:
            checkpoint_path: Path to saved model weights (.pt file).
            device: 'cuda', 'cpu', or None (auto-detect).
        """
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        logger.info("Flood inference device: %s", self.device)

        self.model = FloodUNet()

        if checkpoint_path and checkpoint_path.exists():
            state_dict = torch.load(checkpoint_path, map_location=self.device)
            self.model.load_state_dict(state_dict)
            logger.info("Loaded model weights from %s", checkpoint_path)

        self.model.to(self.device)
        self.model.eval()

    @torch.no_grad()
    def predict(
        self,
        vv_log_ratio: np.ndarray,
        vh_log_ratio: np.ndarray,
        tile_size: int = TILE_SIZE,
        overlap: int = TILE_OVERLAP,
    ) -> np.ndarray:
        """
        Run flood segmentation inference on full-resolution log-ratio images.

        Splits into overlapping tiles, predicts each, and reassembles
        with weighted blending in overlap zones.

        Args:
            vv_log_ratio: VV log-ratio array (H, W), float32.
            vh_log_ratio: VH log-ratio array (H, W), float32.
            tile_size: Tile size for inference.
            overlap: Pixel overlap between tiles.

        Returns:
            Flood probability map (H, W), values 0.0 to 1.0.
        """
        h, w = vv_log_ratio.shape
        logger.info("Running inference on %dx%d image...", h, w)

        # Normalize inputs
        vv_norm = self._normalize(vv_log_ratio)
        vh_norm = self._normalize(vh_log_ratio)

        # Initialize output arrays
        prob_sum = np.zeros((h, w), dtype=np.float64)
        weight_sum = np.zeros((h, w), dtype=np.float64)

        # Create blending weight (cosine taper at edges)
        weight_tile = self._create_blend_weight(tile_size)

        stride = tile_size - overlap
        n_tiles = 0

        for y in range(0, h, stride):
            for x in range(0, w, stride):
                # Extract tile (pad if at edge)
                y_end = min(y + tile_size, h)
                x_end = min(x + tile_size, w)

                tile_vv = np.zeros((tile_size, tile_size), dtype=np.float32)
                tile_vh = np.zeros((tile_size, tile_size), dtype=np.float32)

                th = y_end - y
                tw = x_end - x
                tile_vv[:th, :tw] = vv_norm[y:y_end, x:x_end]
                tile_vh[:th, :tw] = vh_norm[y:y_end, x:x_end]

                # Stack channels and create batch
                tile_input = np.stack([tile_vv, tile_vh], axis=0)  # [2, H, W]
                tensor = torch.from_numpy(tile_input).unsqueeze(0).to(self.device)

                # Inference
                pred = self.model(tensor)
                pred_np = pred.squeeze().cpu().numpy()  # [H, W]

                # Accumulate with blending
                w_tile = weight_tile[:th, :tw]
                prob_sum[y:y_end, x:x_end] += pred_np[:th, :tw] * w_tile
                weight_sum[y:y_end, x:x_end] += w_tile

                n_tiles += 1

        # Normalize by weights
        flood_prob = np.where(weight_sum > 0, prob_sum / weight_sum, 0.0)
        flood_prob = flood_prob.astype(np.float32)

        logger.info(
            "Inference complete: %d tiles, prob range=[%.3f, %.3f]",
            n_tiles, flood_prob.min(), flood_prob.max(),
        )

        return flood_prob

    @staticmethod
    def _normalize(array: np.ndarray) -> np.ndarray:
        """Normalize log-ratio to approximately [-1, 1] range."""
        clean = np.nan_to_num(array, nan=0.0)
        # Clip to ±3 (covers ~99.7% of SAR log-ratio distribution)
        clipped = np.clip(clean, -3.0, 3.0)
        return clipped / 3.0  # Now in [-1, 1]

    @staticmethod
    def _create_blend_weight(size: int) -> np.ndarray:
        """Create a 2D cosine blending weight (soft edges for overlap zones)."""
        ramp = np.ones(size, dtype=np.float32)
        taper = min(size // 4, 16)
        ramp[:taper] = np.linspace(0, 1, taper)
        ramp[-taper:] = np.linspace(1, 0, taper)
        return np.outer(ramp, ramp)
