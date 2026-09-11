from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from app.semantic.base import EmbeddingEvidence, SEMANTIC_MODEL_NAME, SEMANTIC_MODEL_VERSION

logger = logging.getLogger(__name__)

MODEL_SOURCE = "https://github.com/microsoft/torchgeo"
MODEL_LICENSE = "MIT"
MODEL_CHECKPOINT = "resnet18_sentinel2_rgb_moco-e3a335e3.pth"
MODEL_CHECKPOINT_URL = (
    "https://hf.co/torchgeo/resnet18_sentinel2_rgb_moco/resolve/main/"
    "resnet18_sentinel2_rgb_moco-e3a335e3.pth"
)
MODEL_EXPECTED_BANDS: tuple[str, ...] = ("B04", "B03", "B02")


class SemanticModelLoadError(Exception):
    pass


@dataclass(slots=True)
class _ModelHandle:
    model: Any
    torch: Any
    nnf: Any
    device: str
    input_size: tuple[int, int]
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    load_seconds: float


def _normalize_rgb_patch(rgb_patch: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    if rgb_patch.ndim != 3 or rgb_patch.shape[0] != 3:
        raise SemanticModelLoadError("RGB patch must have shape [3, H, W]")
    if valid_mask.ndim != 2 or valid_mask.shape != rgb_patch.shape[1:]:
        raise SemanticModelLoadError("RGB valid-mask shape mismatch")

    normalized = np.nan_to_num(rgb_patch.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    normalized = np.clip(normalized, 0.0, 1.0)
    normalized[:, ~valid_mask] = 0.0
    return normalized


@lru_cache(maxsize=1)
def _load_model() -> _ModelHandle:
    started = time.perf_counter()
    try:
        import torch
        import torch.nn.functional as nnf
        from torchgeo.models import ResNet18_Weights, get_model
    except ImportError as exc:
        raise SemanticModelLoadError("Torch/TorchGeo dependencies are not installed") from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"

    try:
        model = get_model("resnet18", weights=ResNet18_Weights.SENTINEL2_RGB_MOCO)
    except Exception as exc:  # pragma: no cover - runtime model download/registry failures
        raise SemanticModelLoadError("Failed to initialize pretrained TorchGeo model") from exc

    model = model.to(device)
    model.eval()

    pretrained_cfg = getattr(model, "pretrained_cfg", {}) or {}
    raw_input_size = pretrained_cfg.get("input_size", (3, 224, 224))
    if not isinstance(raw_input_size, (tuple, list)) or len(raw_input_size) != 3:
        raw_input_size = (3, 224, 224)

    input_height = int(raw_input_size[1])
    input_width = int(raw_input_size[2])

    mean_values = pretrained_cfg.get("mean", [0.485, 0.456, 0.406])
    std_values = pretrained_cfg.get("std", [0.229, 0.224, 0.225])
    if not isinstance(mean_values, (tuple, list)) or len(mean_values) < 3:
        mean_values = [0.485, 0.456, 0.406]
    if not isinstance(std_values, (tuple, list)) or len(std_values) < 3:
        std_values = [0.229, 0.224, 0.225]

    load_seconds = time.perf_counter() - started
    logger.info(
        "Loaded semantic model name=%s checkpoint=%s device=%s input=%sx%s load_seconds=%.3f",
        SEMANTIC_MODEL_NAME,
        MODEL_CHECKPOINT,
        device,
        input_width,
        input_height,
        load_seconds,
    )

    return _ModelHandle(
        model=model,
        torch=torch,
        nnf=nnf,
        device=device,
        input_size=(input_height, input_width),
        mean=(float(mean_values[0]), float(mean_values[1]), float(mean_values[2])),
        std=(float(std_values[0]), float(std_values[1]), float(std_values[2])),
        load_seconds=load_seconds,
    )


def get_model_provenance() -> dict[str, Any]:
    return {
        "model_name": SEMANTIC_MODEL_NAME,
        "model_version": SEMANTIC_MODEL_VERSION,
        "checkpoint": MODEL_CHECKPOINT,
        "checkpoint_url": MODEL_CHECKPOINT_URL,
        "source": MODEL_SOURCE,
        "license": MODEL_LICENSE,
        "expected_bands": list(MODEL_EXPECTED_BANDS),
    }


def _encode_patch(handle: _ModelHandle, rgb_patch: np.ndarray, valid_mask: np.ndarray) -> Any:
    normalized_patch = _normalize_rgb_patch(rgb_patch, valid_mask)

    torch = handle.torch
    nnf = handle.nnf

    tensor = torch.from_numpy(normalized_patch).unsqueeze(0).to(device=handle.device, dtype=torch.float32)
    tensor = nnf.interpolate(
        tensor,
        size=handle.input_size,
        mode="bilinear",
        align_corners=False,
    )

    mean = torch.tensor(handle.mean, dtype=torch.float32, device=handle.device).view(1, 3, 1, 1)
    std = torch.tensor(handle.std, dtype=torch.float32, device=handle.device).view(1, 3, 1, 1)
    tensor = (tensor - mean) / std

    with torch.inference_mode():
        if hasattr(handle.model, "forward_features"):
            features = handle.model.forward_features(tensor)
        else:  # pragma: no cover - fallback path
            features = handle.model(tensor)

    if features.ndim == 4:
        features = features.mean(dim=(2, 3))
    if features.ndim != 2:
        raise SemanticModelLoadError("Unexpected embedding tensor shape from semantic model")

    return features.squeeze(0)


def compute_embedding_change(
    *,
    before_rgb_patch: np.ndarray,
    after_rgb_patch: np.ndarray,
    valid_mask: np.ndarray,
) -> EmbeddingEvidence:
    handle = _load_model()
    started = time.perf_counter()

    before_embedding = _encode_patch(handle, before_rgb_patch, valid_mask)
    after_embedding = _encode_patch(handle, after_rgb_patch, valid_mask)

    torch = handle.torch
    similarity = float(torch.nn.functional.cosine_similarity(before_embedding, after_embedding, dim=0).item())
    similarity = max(-1.0, min(1.0, similarity))
    distance = float(max(0.0, 1.0 - similarity))

    inference_seconds = time.perf_counter() - started

    return EmbeddingEvidence(
        distance=distance,
        similarity=similarity,
        embedding_dim=int(before_embedding.shape[0]),
        input_height=handle.input_size[0],
        input_width=handle.input_size[1],
        normalization_mean=handle.mean,
        normalization_std=handle.std,
        device=handle.device,
        inference_seconds=inference_seconds,
        model_load_seconds=handle.load_seconds,
    )
