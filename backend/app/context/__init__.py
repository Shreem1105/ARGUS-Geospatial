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
from app.context.osm import OpenStreetMapProvider


def get_context_provider() -> ContextProvider:
    return OpenStreetMapProvider()


__all__ = [
    "ContextFeatureCandidate",
    "ContextFetchResult",
    "ContextProvider",
    "ContextProviderError",
    "ContextProviderLimitExceededError",
    "FEATURE_TYPE_ADMINISTRATIVE",
    "FEATURE_TYPE_BUILDING",
    "FEATURE_TYPE_ROAD",
    "FEATURE_TYPE_WATERWAY",
    "OpenStreetMapProvider",
    "SUPPORTED_CONTEXT_FEATURE_TYPES",
    "get_context_provider",
]
