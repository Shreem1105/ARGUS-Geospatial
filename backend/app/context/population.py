from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

CENSUS_PROVIDER_NAME = "us_census"
CENSUS_ATTRIBUTION = "Source: U.S. Census Bureau"

TIGERWEB_TRACTS_BLOCKS_BASE_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer"
)
TIGERWEB_BLOCK_GROUP_LAYER_ID = 8

CENSUS2020_TRACTS_BASE_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/Tracts_Blocks/MapServer"
)
CENSUS2020_TRACT_LAYER_ID = 8

DEFAULT_ACS_YEAR = "2024"
ACS_DATASET = "acs5_total_population_block_group"
CENSUS2020_DATASET = "census2020_pop100_tract"
CENSUS2020_DATASET_VERSION = "decennial_2020"


class PopulationProviderError(Exception):
    pass


class PopulationProviderLimitExceededError(PopulationProviderError):
    pass


@dataclass(slots=True)
class PopulationFeatureCandidate:
    source_feature_id: str
    geography_type: str
    name: str | None
    population: int | None
    geometry: dict[str, Any]
    properties: dict[str, Any]
    source_updated_at: datetime | None = None


@dataclass(slots=True)
class PopulationFetchResult:
    provider: str
    dataset: str
    dataset_version: str
    attribution: str
    geography_type: str
    fetched_count: int
    skipped_count: int
    features: list[PopulationFeatureCandidate]


class PopulationProvider(Protocol):
    provider_name: str
    attribution: str

    def fetch_population_units(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> PopulationFetchResult: ...


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    normalized = value.strip()
    return normalized or None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _build_esri_polygon(geometry: dict[str, Any]) -> dict[str, Any]:
    if geometry.get("type") != "Polygon":
        raise PopulationProviderError("monitor geometry must be a Polygon")

    rings = geometry.get("coordinates")
    if not isinstance(rings, list) or not rings:
        raise PopulationProviderError("monitor polygon coordinates are invalid")

    esri_rings: list[list[list[float]]] = []
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4:
            continue

        parsed_ring: list[list[float]] = []
        for point in ring:
            if not isinstance(point, list) or len(point) != 2:
                continue
            lon, lat = point
            if isinstance(lon, bool) or isinstance(lat, bool):
                continue
            if not isinstance(lon, (float, int)) or not isinstance(lat, (float, int)):
                continue
            parsed_ring.append([float(lon), float(lat)])

        if len(parsed_ring) < 4:
            continue

        esri_rings.append(parsed_ring)

    if not esri_rings:
        raise PopulationProviderError("monitor polygon ring is invalid")

    return {"rings": esri_rings, "spatialReference": {"wkid": 4326}}


class CensusPopulationProvider:
    provider_name = CENSUS_PROVIDER_NAME
    attribution = CENSUS_ATTRIBUTION
    dataset = ACS_DATASET

    def __init__(
        self,
        *,
        tigerweb_base_url: str = TIGERWEB_TRACTS_BLOCKS_BASE_URL,
        block_group_layer_id: int = TIGERWEB_BLOCK_GROUP_LAYER_ID,
        fallback_base_url: str = CENSUS2020_TRACTS_BASE_URL,
        fallback_layer_id: int = CENSUS2020_TRACT_LAYER_ID,
        acs_year: str = DEFAULT_ACS_YEAR,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.tigerweb_base_url = tigerweb_base_url.rstrip("/")
        self.block_group_layer_id = block_group_layer_id
        self.fallback_base_url = fallback_base_url.rstrip("/")
        self.fallback_layer_id = fallback_layer_id
        self.acs_year = str(acs_year)
        self.timeout_seconds = timeout_seconds

    @property
    def dataset_version(self) -> str:
        return f"acs5_{self.acs_year}"

    def _query_geometry_features(
        self,
        *,
        base_url: str,
        layer_id: int,
        out_fields: str,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> list[dict[str, Any]]:
        endpoint = f"{base_url}/{layer_id}/query"
        esri_geometry = _build_esri_polygon(intersects_geometry)
        params = {
            "f": "geojson",
            "where": "1=1",
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": "4326",
            "inSR": "4326",
            "geometryType": "esriGeometryPolygon",
            "geometry": json.dumps(esri_geometry),
            "spatialRel": "esriSpatialRelIntersects",
            "resultRecordCount": str(max_features),
            "orderByFields": "GEOID",
        }

        try:
            response = httpx.get(
                endpoint,
                params=params,
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise PopulationProviderError("Failed to query Census geographies") from exc

        if isinstance(payload, dict) and "error" in payload:
            raise PopulationProviderError("Census geography query returned an error response")

        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            raise PopulationProviderError("Census geography response is malformed")

        if len(features) > max_features:
            raise PopulationProviderLimitExceededError("Population provider response exceeded configured limit")

        return features

    def _query_block_group_geometries(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> list[dict[str, Any]]:
        return self._query_geometry_features(
            base_url=self.tigerweb_base_url,
            layer_id=self.block_group_layer_id,
            out_fields="GEOID,STATE,COUNTY,TRACT,BLKGRP,NAME,BASENAME,OBJECTID",
            intersects_geometry=intersects_geometry,
            max_features=max_features,
        )

    def _query_census2020_tract_geometries(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> list[dict[str, Any]]:
        return self._query_geometry_features(
            base_url=self.fallback_base_url,
            layer_id=self.fallback_layer_id,
            out_fields="GEOID,STATE,COUNTY,TRACT,NAME,BASENAME,OBJECTID,POP100",
            intersects_geometry=intersects_geometry,
            max_features=max_features,
        )

    def _fetch_county_populations(
        self,
        *,
        state_fips: str,
        county_fips: str,
    ) -> dict[str, int]:
        endpoint = f"https://api.census.gov/data/{self.acs_year}/acs/acs5"
        params = {
            "get": "NAME,B01003_001E",
            "for": "block group:*",
            "in": f"state:{state_fips} county:{county_fips}",
        }

        try:
            response = httpx.get(
                endpoint,
                params=params,
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise PopulationProviderError("Failed to query Census ACS population data") from exc

        if not isinstance(payload, list) or not payload:
            raise PopulationProviderError("Census ACS response is malformed")

        rows = payload[1:]
        population_by_geoid: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                continue

            population = _as_int(row[1])
            if population is None:
                continue

            state = _normalize_text(row[3])
            county = _normalize_text(row[4])
            tract = _normalize_text(row[5])
            block_group = _normalize_text(row[2])
            if not state or not county or not tract or not block_group:
                continue

            geoid = f"{state}{county}{tract}{block_group}"
            population_by_geoid[geoid] = population

        return population_by_geoid

    def _acs_candidates(self, raw_features: list[dict[str, Any]]) -> tuple[list[PopulationFeatureCandidate], int]:
        county_pairs: set[tuple[str, str]] = set()
        for feature in raw_features:
            props = feature.get("properties")
            if not isinstance(props, dict):
                continue
            state = _normalize_text(props.get("STATE"))
            county = _normalize_text(props.get("COUNTY"))
            if state and county:
                county_pairs.add((state, county))

        population_lookup: dict[str, int] = {}
        for state_fips, county_fips in sorted(county_pairs):
            population_lookup.update(
                self._fetch_county_populations(
                    state_fips=state_fips,
                    county_fips=county_fips,
                )
            )

        candidates: list[PopulationFeatureCandidate] = []
        skipped = 0

        for feature in raw_features:
            geometry = feature.get("geometry")
            properties = feature.get("properties")
            if not isinstance(geometry, dict) or not isinstance(properties, dict):
                skipped += 1
                continue

            geoid = _normalize_text(properties.get("GEOID"))
            if geoid is None:
                skipped += 1
                continue

            block_group = _normalize_text(properties.get("BLKGRP"))
            tract = _normalize_text(properties.get("TRACT"))
            state = _normalize_text(properties.get("STATE"))
            county = _normalize_text(properties.get("COUNTY"))

            candidate_properties = {
                "geoid": geoid,
                "state_fips": state,
                "county_fips": county,
                "tract": tract,
                "block_group": block_group,
                "name": _normalize_text(properties.get("NAME")),
                "basename": _normalize_text(properties.get("BASENAME")),
                "source_layer": f"Tracts_Blocks/{self.block_group_layer_id}",
                "population_table": "B01003_001E",
                "provider_attribution": self.attribution,
            }

            candidates.append(
                PopulationFeatureCandidate(
                    source_feature_id=geoid,
                    geography_type="block_group",
                    name=_normalize_text(properties.get("NAME")) or _normalize_text(properties.get("BASENAME")),
                    population=population_lookup.get(geoid),
                    geometry=geometry,
                    properties={key: value for key, value in candidate_properties.items() if value is not None},
                    source_updated_at=None,
                )
            )

        return candidates, skipped

    def _census2020_candidates(self, raw_features: list[dict[str, Any]]) -> tuple[list[PopulationFeatureCandidate], int]:
        candidates: list[PopulationFeatureCandidate] = []
        skipped = 0

        for feature in raw_features:
            geometry = feature.get("geometry")
            properties = feature.get("properties")
            if not isinstance(geometry, dict) or not isinstance(properties, dict):
                skipped += 1
                continue

            geoid = _normalize_text(properties.get("GEOID"))
            if geoid is None:
                skipped += 1
                continue

            candidate_properties = {
                "geoid": geoid,
                "state_fips": _normalize_text(properties.get("STATE")),
                "county_fips": _normalize_text(properties.get("COUNTY")),
                "tract": _normalize_text(properties.get("TRACT")),
                "name": _normalize_text(properties.get("NAME")),
                "basename": _normalize_text(properties.get("BASENAME")),
                "source_layer": f"Census2020_Tracts_Blocks/{self.fallback_layer_id}",
                "population_table": "POP100",
                "provider_attribution": self.attribution,
            }

            candidates.append(
                PopulationFeatureCandidate(
                    source_feature_id=geoid,
                    geography_type="tract",
                    name=_normalize_text(properties.get("NAME")) or _normalize_text(properties.get("BASENAME")),
                    population=_as_int(properties.get("POP100")),
                    geometry=geometry,
                    properties={key: value for key, value in candidate_properties.items() if value is not None},
                    source_updated_at=None,
                )
            )

        return candidates, skipped

    def fetch_population_units(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> PopulationFetchResult:
        try:
            raw_features = self._query_block_group_geometries(
                intersects_geometry=intersects_geometry,
                max_features=max_features,
            )
            candidates, skipped = self._acs_candidates(raw_features)

            logger.info(
                "Fetched census population units via ACS geographies=%s candidates=%s skipped=%s",
                len(raw_features),
                len(candidates),
                skipped,
            )

            return PopulationFetchResult(
                provider=self.provider_name,
                dataset=self.dataset,
                dataset_version=self.dataset_version,
                attribution=self.attribution,
                geography_type="block_group",
                fetched_count=len(candidates),
                skipped_count=skipped,
                features=candidates,
            )
        except PopulationProviderLimitExceededError:
            raise
        except PopulationProviderError as exc:
            logger.warning(
                "ACS population lookup failed; falling back to Census2020 POP100 provider=%s reason=%s",
                self.provider_name,
                exc,
            )

        raw_features = self._query_census2020_tract_geometries(
            intersects_geometry=intersects_geometry,
            max_features=max_features,
        )
        candidates, skipped = self._census2020_candidates(raw_features)

        logger.info(
            "Fetched census population units via Census2020 POP100 geographies=%s candidates=%s skipped=%s",
            len(raw_features),
            len(candidates),
            skipped,
        )

        return PopulationFetchResult(
            provider=self.provider_name,
            dataset=CENSUS2020_DATASET,
            dataset_version=CENSUS2020_DATASET_VERSION,
            attribution=self.attribution,
            geography_type="tract",
            fetched_count=len(candidates),
            skipped_count=skipped,
            features=candidates,
        )

