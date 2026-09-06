from app.satellite.base import SatelliteProvider, SatelliteProviderError, SatelliteSearchResult
from app.satellite.planetary_computer import PlanetaryComputerProvider


def get_satellite_provider() -> SatelliteProvider:
    return PlanetaryComputerProvider()


__all__ = [
    "PlanetaryComputerProvider",
    "SatelliteProvider",
    "SatelliteProviderError",
    "SatelliteSearchResult",
    "get_satellite_provider",
]
