from __future__ import annotations

from app.context.population import (
    CENSUS2020_DATASET,
    CENSUS2020_DATASET_VERSION,
    CensusPopulationProvider,
    PopulationProviderError,
)


def _geometry() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[-80.8530, 35.2220], [-80.8455, 35.2220], [-80.8455, 35.2295], [-80.8530, 35.2295], [-80.8530, 35.2220]]],
    }


def test_population_provider_uses_acs_when_available(monkeypatch) -> None:
    provider = CensusPopulationProvider()

    monkeypatch.setattr(
        provider,
        "_query_block_group_geometries",
        lambda **_: [
            {
                "geometry": _geometry(),
                "properties": {
                    "GEOID": "370670001001",
                    "STATE": "37",
                    "COUNTY": "067",
                    "TRACT": "000100",
                    "BLKGRP": "1",
                    "NAME": "BG 1",
                    "BASENAME": "1",
                },
            }
        ],
    )
    monkeypatch.setattr(
        provider,
        "_fetch_county_populations",
        lambda **_: {"370670001001": 1234},
    )

    result = provider.fetch_population_units(
        intersects_geometry=_geometry(),
        max_features=100,
    )

    assert result.dataset == "acs5_total_population_block_group"
    assert result.dataset_version.startswith("acs5_")
    assert result.geography_type == "block_group"
    assert result.fetched_count == 1
    assert result.features[0].population == 1234


def test_population_provider_falls_back_to_census2020_when_acs_fails(monkeypatch) -> None:
    provider = CensusPopulationProvider()

    monkeypatch.setattr(
        provider,
        "_query_block_group_geometries",
        lambda **_: [
            {
                "geometry": _geometry(),
                "properties": {
                    "GEOID": "370670001001",
                    "STATE": "37",
                    "COUNTY": "067",
                    "TRACT": "000100",
                    "BLKGRP": "1",
                    "NAME": "BG 1",
                    "BASENAME": "1",
                },
            }
        ],
    )

    def _raise_acs_error(**_: object) -> dict[str, int]:
        raise PopulationProviderError("ACS unavailable")

    monkeypatch.setattr(provider, "_fetch_county_populations", _raise_acs_error)
    monkeypatch.setattr(
        provider,
        "_query_census2020_tract_geometries",
        lambda **_: [
            {
                "geometry": _geometry(),
                "properties": {
                    "GEOID": "37067000100",
                    "STATE": "37",
                    "COUNTY": "067",
                    "TRACT": "000100",
                    "NAME": "Tract 1",
                    "BASENAME": "1",
                    "POP100": 777,
                },
            }
        ],
    )

    result = provider.fetch_population_units(
        intersects_geometry=_geometry(),
        max_features=100,
    )

    assert result.dataset == CENSUS2020_DATASET
    assert result.dataset_version == CENSUS2020_DATASET_VERSION
    assert result.geography_type == "tract"
    assert result.fetched_count == 1
    assert result.features[0].source_feature_id == "37067000100"
    assert result.features[0].population == 777

