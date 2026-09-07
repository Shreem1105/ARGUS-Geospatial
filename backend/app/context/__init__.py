from app.context.base import (
    FEATURE_TYPE_ADMINISTRATIVE,
    FEATURE_TYPE_BUILDING,
    FEATURE_TYPE_ROAD,
    FEATURE_TYPE_WATERWAY,
    SUPPORTED_CONTEXT_FEATURE_TYPES,
    ContextFeatureCandidate,
    ContextFetchResult,
    ContextProvider,
    ContextProviderError,
    ContextProviderLimitExceededError,
)
from app.context.environment import (
    EnvironmentalFeatureCandidate,
    EnvironmentalFetchResult,
    EnvironmentalProvider,
    EnvironmentalProviderError,
    EnvironmentalProviderLimitExceededError,
    OpenStreetMapEnvironmentalProvider,
)
from app.context.landcover import (
    LandCoverClassBreakdown,
    LandCoverExposureResult,
    LandCoverProvider,
    LandCoverProviderError,
    LandCoverSourceCandidate,
    PlanetaryComputerLandCoverProvider,
)
from app.context.osm import OpenStreetMapProvider
from app.context.population import (
    CensusPopulationProvider,
    PopulationFeatureCandidate,
    PopulationFetchResult,
    PopulationProvider,
    PopulationProviderError,
    PopulationProviderLimitExceededError,
)


def get_context_provider() -> ContextProvider:
    return OpenStreetMapProvider()


def get_population_provider() -> PopulationProvider:
    return CensusPopulationProvider()


def get_land_cover_provider() -> LandCoverProvider:
    return PlanetaryComputerLandCoverProvider()


def get_environmental_provider() -> EnvironmentalProvider:
    return OpenStreetMapEnvironmentalProvider()


__all__ = [
    "ContextFeatureCandidate",
    "ContextFetchResult",
    "ContextProvider",
    "ContextProviderError",
    "ContextProviderLimitExceededError",
    "EnvironmentalFeatureCandidate",
    "EnvironmentalFetchResult",
    "EnvironmentalProvider",
    "EnvironmentalProviderError",
    "EnvironmentalProviderLimitExceededError",
    "FEATURE_TYPE_ADMINISTRATIVE",
    "FEATURE_TYPE_BUILDING",
    "FEATURE_TYPE_ROAD",
    "FEATURE_TYPE_WATERWAY",
    "LandCoverClassBreakdown",
    "LandCoverExposureResult",
    "LandCoverProvider",
    "LandCoverProviderError",
    "LandCoverSourceCandidate",
    "OpenStreetMapProvider",
    "OpenStreetMapEnvironmentalProvider",
    "PopulationFeatureCandidate",
    "PopulationFetchResult",
    "PopulationProvider",
    "PopulationProviderError",
    "PopulationProviderLimitExceededError",
    "CensusPopulationProvider",
    "PlanetaryComputerLandCoverProvider",
    "SUPPORTED_CONTEXT_FEATURE_TYPES",
    "get_context_provider",
    "get_population_provider",
    "get_land_cover_provider",
    "get_environmental_provider",
]
