from __future__ import annotations

from app.semantic.base import EventSpectralEvidence, SemanticInferenceOutcome

MIN_VALID_PIXEL_COVERAGE = 0.20
MIN_EVIDENCE_STRENGTH = 0.30


def _scaled_magnitude(value: float | None, scale: float) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(abs(float(value)) / scale, 1.0))


def _compute_signal_scores(
    *,
    ndvi_delta: float | None,
    ndwi_delta: float | None,
    built_up_delta: float | None,
    nbr_delta: float | None,
) -> dict[str, float]:
    scores = {
        "vegetation_decrease": 0.0,
        "vegetation_increase": 0.0,
        "built_area_increase": 0.0,
        "built_area_decrease": 0.0,
        "water_expansion": 0.0,
        "water_contraction": 0.0,
        "bare_ground_increase": 0.0,
        "bare_ground_decrease": 0.0,
    }

    if ndvi_delta is not None:
        if ndvi_delta < 0:
            scores["vegetation_decrease"] += _scaled_magnitude(ndvi_delta, 0.35)
        if ndvi_delta > 0:
            scores["vegetation_increase"] += _scaled_magnitude(ndvi_delta, 0.35)

    if ndwi_delta is not None:
        if ndwi_delta > 0:
            scores["water_expansion"] += _scaled_magnitude(ndwi_delta, 0.30)
        if ndwi_delta < 0:
            scores["water_contraction"] += _scaled_magnitude(ndwi_delta, 0.30)

    if built_up_delta is not None:
        if built_up_delta > 0:
            scores["built_area_increase"] += _scaled_magnitude(built_up_delta, 0.30)
        if built_up_delta < 0:
            scores["built_area_decrease"] += _scaled_magnitude(built_up_delta, 0.30)

    if nbr_delta is not None:
        if nbr_delta < 0:
            scores["bare_ground_increase"] += _scaled_magnitude(nbr_delta, 0.30)
        if nbr_delta > 0:
            scores["bare_ground_decrease"] += _scaled_magnitude(nbr_delta, 0.30)

    if ndvi_delta is not None and ndvi_delta < -0.10 and (built_up_delta is None or built_up_delta < 0.05):
        scores["bare_ground_increase"] += 0.20

    if ndvi_delta is not None and ndvi_delta > 0.10 and (built_up_delta is None or built_up_delta < 0.05):
        scores["bare_ground_decrease"] += 0.15

    if built_up_delta is not None and built_up_delta > 0 and ndvi_delta is not None and ndvi_delta < 0:
        scores["built_area_increase"] += 0.20

    if built_up_delta is not None and built_up_delta < 0 and ndvi_delta is not None and ndvi_delta > 0:
        scores["built_area_decrease"] += 0.20

    return {label: min(1.0, max(0.0, score)) for label, score in scores.items()}


def _format_change(before_value: float | None, after_value: float | None, delta: float | None) -> str:
    if before_value is None or after_value is None or delta is None:
        return "not available"
    return f"{before_value:.3f} -> {after_value:.3f} (Δ {delta:+.3f})"


def infer_semantic_change(
    *,
    spectral: EventSpectralEvidence,
    embedding_distance: float | None,
    baseline_land_cover: str | None,
) -> SemanticInferenceOutcome:
    scores = _compute_signal_scores(
        ndvi_delta=spectral.ndvi_delta,
        ndwi_delta=spectral.ndwi_delta,
        built_up_delta=spectral.built_up_delta,
        nbr_delta=spectral.nbr_delta,
    )

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_label, best_score = ranked[0] if ranked else ("uncertain", 0.0)
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    embedding_strength = 0.0 if embedding_distance is None else min(1.0, max(0.0, embedding_distance / 0.45))
    coverage_strength = min(1.0, max(0.0, spectral.valid_pixel_coverage / 0.85))
    agreement = 1.0 if best_score <= 0 else max(0.0, min(1.0, 1.0 - (second_score / (best_score + 1e-6))))

    abstention_reasons: list[str] = []
    abstained = False

    if spectral.valid_pixel_coverage < MIN_VALID_PIXEL_COVERAGE:
        abstained = True
        abstention_reasons.append("insufficient_valid_pixel_coverage")

    if best_score < MIN_EVIDENCE_STRENGTH:
        abstained = True
        abstention_reasons.append("weak_semantic_evidence")

    if best_score >= MIN_EVIDENCE_STRENGTH and second_score >= MIN_EVIDENCE_STRENGTH and abs(best_score - second_score) <= 0.10:
        best_label = "mixed_change"
        abstained = False

    if abstained:
        semantic_label = "uncertain"
    else:
        semantic_label = best_label

    semantic_confidence = (
        (0.45 * max(best_score, second_score if semantic_label == "mixed_change" else best_score))
        + (0.20 * embedding_strength)
        + (0.20 * coverage_strength)
        + (0.15 * agreement)
    )
    semantic_confidence = max(0.0, min(1.0, float(semantic_confidence)))

    if semantic_label == "uncertain":
        semantic_confidence = min(semantic_confidence, 0.45)
    elif semantic_label == "mixed_change":
        semantic_confidence = min(max(semantic_confidence, 0.35), 0.75)

    explanation = [
        f"Valid comparison coverage inside event footprint: {spectral.valid_pixel_coverage * 100:.1f}% ({spectral.valid_pixel_count}/{spectral.total_event_pixel_count} pixels).",
        f"NDVI: {_format_change(spectral.before_ndvi_mean, spectral.after_ndvi_mean, spectral.ndvi_delta)}.",
        f"NDWI: {_format_change(spectral.before_ndwi_mean, spectral.after_ndwi_mean, spectral.ndwi_delta)}.",
        f"Built-up index (NDBI): {_format_change(spectral.before_built_up_score, spectral.after_built_up_score, spectral.built_up_delta)}.",
        f"Burn/soil index (NBR): {_format_change(spectral.before_nbr_mean, spectral.after_nbr_mean, spectral.nbr_delta)}.",
    ]

    if embedding_distance is None:
        explanation.append("Embedding representation distance was unavailable for this event patch.")
    else:
        explanation.append(f"Embedding cosine distance between before/after event patches: {embedding_distance:.3f}.")

    if baseline_land_cover is not None:
        explanation.append(
            f"Baseline WorldCover dominant class context: {baseline_land_cover} (contextual baseline, not a temporal per-scene label)."
        )
    else:
        explanation.append("Baseline WorldCover class context was unavailable at semantic computation time.")

    if abstained:
        explanation.append(
            "Semantic classifier abstained and returned uncertain because available evidence did not meet reliability thresholds."
        )

    explanation.append(
        "Semantic evidence confidence reflects agreement and signal strength of observable change evidence; it is not a calibrated probability."
    )

    diagnostics = {
        "best_score": round(float(best_score), 6),
        "second_score": round(float(second_score), 6),
        "agreement": round(float(agreement), 6),
        "coverage_strength": round(float(coverage_strength), 6),
        "embedding_strength": round(float(embedding_strength), 6),
    }

    return SemanticInferenceOutcome(
        semantic_label=semantic_label,
        semantic_confidence=round(semantic_confidence, 6),
        abstained=abstained,
        explanation=explanation,
        signal_scores={label: round(float(value), 6) for label, value in scores.items()},
        abstention_reasons=abstention_reasons,
        diagnostics=diagnostics,
    )
