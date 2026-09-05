import math
from datetime import timedelta
from django.utils import timezone

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

def detect_anomalies(records: list) -> list[str]:
    anomalies = set()
    
    if not records:
        return list(anomalies)
        
    for i in range(1, len(records)):
        prev = records[i-1]
        curr = records[i]
        
        dt = (curr.timestamp - prev.timestamp).total_seconds()
        
        if dt > 1800:
            anomalies.add('ais_gap')
            
        if dt <= 600 and prev.speed_knots is not None and curr.speed_knots is not None:
            if abs(curr.speed_knots - prev.speed_knots) > 5:
                anomalies.add('speed_change')
                
    if len(records) >= 3:
        for i in range(len(records)):
            for j in range(i+1, len(records)):
                dist = haversine_km(records[i].lat, records[i].lon, records[j].lat, records[j].lon)
                if dist <= 2.0:
                    dt = (records[j].timestamp - records[i].timestamp).total_seconds()
                    if dt > 3600:
                        anomalies.add('loitering')
                        break
                else:
                    break
                    
    return list(anomalies)

def score_vessels(drift_result, search_radius_km=50.0, time_window_hours=48.0,
                  w_proximity=0.4, w_temporal=0.35, w_behavioral=0.25):
    from .models import AISRecord, SuspectScore
    
    origin_lat = drift_result.origin_lat
    origin_lon = drift_result.origin_lon
    origin_time = drift_result.origin_time
    
    start_time = origin_time - timedelta(hours=time_window_hours)
    end_time = origin_time + timedelta(hours=time_window_hours)
    
    records = AISRecord.objects.filter(
        timestamp__gte=start_time,
        timestamp__lte=end_time
    ).select_related('vessel').order_by('vessel_id', 'timestamp')
    
    vessel_groups = {}
    for r in records:
        vessel_groups.setdefault(r.vessel, []).append(r)
        
    scores = []
    
    for vessel, recs in vessel_groups.items():
        min_dist = float('inf')
        closest_rec = None
        closest_time_rec = None
        min_time_diff = float('inf')
        
        for r in recs:
            dist = haversine_km(origin_lat, origin_lon, r.lat, r.lon)
            if dist < min_dist:
                min_dist = dist
                closest_rec = r
                
            time_diff = abs((r.timestamp - origin_time).total_seconds()) / 3600.0
            if time_diff < min_time_diff:
                min_time_diff = time_diff
                closest_time_rec = r
                
        if min_dist > search_radius_km:
            continue
            
        anomalies = detect_anomalies(recs)
        
        proximity_score = math.exp(-min_dist / 10.0)
        temporal_score = math.exp(-min_time_diff / 6.0)
        behavioral_score = min(len(anomalies) * 0.33, 1.0)
        
        composite = (w_proximity * proximity_score +
                     w_temporal * temporal_score +
                     w_behavioral * behavioral_score)
                     
        scores.append(SuspectScore(
            drift_result=drift_result,
            vessel=vessel,
            proximity_score=proximity_score,
            temporal_score=temporal_score,
            behavioral_score=behavioral_score,
            composite_score=composite,
            min_distance_km=min_dist,
            closest_time=closest_time_rec.timestamp if closest_time_rec else closest_rec.timestamp,
            anomalies_detected=anomalies,
            rank=0
        ))
        
    scores.sort(key=lambda x: x.composite_score, reverse=True)
    for i, s in enumerate(scores):
        s.rank = i + 1
        
    return scores
