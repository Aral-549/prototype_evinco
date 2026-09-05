from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DriftInput:
    """Input parameters for drift computation."""
    start_lat: float
    start_lon: float
    detection_time: datetime
    wind_speed_mps: float = 5.0
    wind_direction_deg: float = 180.0  # direction wind is coming FROM
    current_speed_mps: float = 0.3
    current_direction_deg: float = 90.0  # direction current is flowing TO
    duration_hours: float = 24.0
    time_step_hours: float = 1.0


@dataclass
class DriftOutput:
    """Output of drift computation."""
    origin_lat: float
    origin_lon: float
    origin_time: datetime
    origin_uncertainty_km: float
    hindcast_trajectory: list  # [{"lat", "lon", "time"}, ...]
    forecast_trajectory: list


class DriftEngine(ABC):
    """Abstract interface for drift computation engines."""
    name: str = 'base'

    @abstractmethod
    def compute(self, params: DriftInput) -> DriftOutput:
        ...
