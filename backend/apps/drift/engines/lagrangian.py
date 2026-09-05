import math
from datetime import timedelta
from .base import DriftEngine, DriftInput, DriftOutput

class LagrangianDriftEngine(DriftEngine):
    name = 'lagrangian'

    def compute(self, params: DriftInput) -> DriftOutput:
        R_earth_meters = 6_371_000
        alpha = 0.03
        
        # Wind (coming FROM)
        wind_dir_rad = math.radians(params.wind_direction_deg)
        wind_east = -params.wind_speed_mps * math.sin(wind_dir_rad)
        wind_north = -params.wind_speed_mps * math.cos(wind_dir_rad)
        
        # Current (going TO)
        curr_dir_rad = math.radians(params.current_direction_deg)
        curr_east = params.current_speed_mps * math.sin(curr_dir_rad)
        curr_north = params.current_speed_mps * math.cos(curr_dir_rad)
        
        # Drift velocity
        v_east = curr_east + alpha * wind_east
        v_north = curr_north + alpha * wind_north
        
        # Time setup
        dt_hours = params.time_step_hours
        dt_seconds = dt_hours * 3600
        steps = int(params.duration_hours / dt_hours)
        
        hindcast = []
        forecast = []
        
        # Add initial point to both
        hindcast.append({
            "lat": params.start_lat,
            "lon": params.start_lon,
            "time": params.detection_time.isoformat()
        })
        forecast.append({
            "lat": params.start_lat,
            "lon": params.start_lon,
            "time": params.detection_time.isoformat()
        })
        
        # Hindcast (backward)
        current_lat = params.start_lat
        current_lon = params.start_lon
        current_time = params.detection_time
        
        for _ in range(steps):
            lat_rad = math.radians(current_lat)
            new_lat = current_lat - (v_north * dt_seconds) / R_earth_meters * (180/math.pi)
            new_lon = current_lon - (v_east * dt_seconds) / (R_earth_meters * math.cos(lat_rad)) * (180/math.pi)
            current_time -= timedelta(hours=dt_hours)
            current_lat = new_lat
            current_lon = new_lon
            
            hindcast.append({
                "lat": current_lat,
                "lon": current_lon,
                "time": current_time.isoformat()
            })
            
        origin_lat = current_lat
        origin_lon = current_lon
        origin_time = current_time
        origin_uncertainty = 2.0 + 0.5 * params.duration_hours
        
        # Forecast (forward)
        current_lat = params.start_lat
        current_lon = params.start_lon
        current_time = params.detection_time
        
        for _ in range(steps):
            lat_rad = math.radians(current_lat)
            new_lat = current_lat + (v_north * dt_seconds) / R_earth_meters * (180/math.pi)
            new_lon = current_lon + (v_east * dt_seconds) / (R_earth_meters * math.cos(lat_rad)) * (180/math.pi)
            current_time += timedelta(hours=dt_hours)
            current_lat = new_lat
            current_lon = new_lon
            
            forecast.append({
                "lat": current_lat,
                "lon": current_lon,
                "time": current_time.isoformat()
            })
            
        return DriftOutput(
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            origin_time=origin_time,
            origin_uncertainty_km=origin_uncertainty,
            hindcast_trajectory=hindcast[::-1],
            forecast_trajectory=forecast
        )
