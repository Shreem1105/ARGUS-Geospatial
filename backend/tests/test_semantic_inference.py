from __future__ import annotations

import numpy as np

from app.semantic.base import EventSpectralEvidence
from app.semantic.inference import infer_semantic_change


def _spectral(
    *,
    ndvi_delta: float | None,
    ndwi_delta: float | None,
    built_up_delta: float | None,
    nbr_delta: float | None,
    coverage: float = 0.75,
) -> EventSpectralEvidence:
    valid_pixels = int(coverage * 100)
    return EventSpectralEvidence(
        before_ndvi_mean=(0.5 if ndvi_delta is not None else None),
        after_ndvi_mean=((0.5 + ndvi_delta) if ndvi_delta is not None else None),
        ndvi_delta=ndvi_delta,
        before_ndwi_mean=(0.1 if ndwi_delta is not None else None),
        after_ndwi_mean=((0.1 + ndwi_delta) if ndwi_delta is not None else None),
        ndwi_delta=ndwi_delta,
        before_nbr_mean=(0.2 if nbr_delta is not None else None),
        after_nbr_mean=((0.2 + nbr_delta) if nbr_delta is not None else None),
        nbr_delta=nbr_delta,
        before_built_up_score=(0.15 if built_up_delta is not None else None),
        after_built_up_score=((0.15 + built_up_delta) if built_up_delta is not None else None),
        built_up_delta=built_up_delta,
        valid_pixel_count=valid_pixels,
        total_event_pixel_count=100,
        valid_pixel_coverage=coverage,
        before_rgb_patch=np.zeros((3, 4, 4), dtype=np.float32),
        after_rgb_patch=np.zeros((3, 4, 4), dtype=np.float32),
        patch_valid_mask=np.ones((4, 4), dtype=bool),
        index_availability={"ndvi": True, "ndwi": True, "nbr": True, "ndbi": True},
        notes=[],
    )


def test_infer_vegetation_decrease_when_ndvi_drops() -> None:
    outcome = infer_semantic_change(
        spectral=_spectral(
            ndvi_delta=-0.26,
            ndwi_delta=0.02,
            built_up_delta=0.05,
            nbr_delta=-0.08,
        ),
        embedding_distance=0.32,
        baseline_land_cover="Tree cover",
    )

    assert outcome.semantic_label == "vegetation_decrease"
    assert outcome.abstained is False
    assert outcome.semantic_confidence > 0.35


def test_infer_built_area_increase_when_built_up_rises() -> None:
    outcome = infer_semantic_change(
        spectral=_spectral(
            ndvi_delta=-0.10,
            ndwi_delta=-0.03,
            built_up_delta=0.24,
            nbr_delta=-0.04,
        ),
        embedding_distance=0.41,
        baseline_land_cover="Built-up",
    )

    assert outcome.semantic_label == "built_area_increase"
    assert outcome.abstained is False
    assert outcome.signal_scores["built_area_increase"] >= outcome.signal_scores["vegetation_decrease"]


def test_infer_mixed_change_when_multiple_strong_signals_tie() -> None:
    outcome = infer_semantic_change(
        spectral=_spectral(
            ndvi_delta=-0.14,
            ndwi_delta=0.14,
            built_up_delta=None,
            nbr_delta=None,
        ),
        embedding_distance=0.18,
        baseline_land_cover="Shrubland",
    )

    assert outcome.semantic_label == "mixed_change"
    assert outcome.abstained is False


def test_infer_abstains_for_insufficient_valid_pixels() -> None:
    outcome = infer_semantic_change(
        spectral=_spectral(
            ndvi_delta=-0.28,
            ndwi_delta=0.01,
            built_up_delta=0.03,
            nbr_delta=-0.02,
            coverage=0.08,
        ),
        embedding_distance=0.25,
        baseline_land_cover=None,
    )

    assert outcome.semantic_label == "uncertain"
    assert outcome.abstained is True
    assert "insufficient_valid_pixel_coverage" in outcome.abstention_reasons


def test_explanation_includes_confidence_disclaimer() -> None:
    outcome = infer_semantic_change(
        spectral=_spectral(
            ndvi_delta=0.09,
            ndwi_delta=-0.04,
            built_up_delta=-0.06,
            nbr_delta=0.07,
        ),
        embedding_distance=None,
        baseline_land_cover="Grassland",
    )

    assert any("not a calibrated probability" in line for line in outcome.explanation)
