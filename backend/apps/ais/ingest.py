import pandas as pd
import numpy as np
from .models import Vessel, AISRecord

def ingest_ais_csv(file_path: str, batch_size: int = 5000) -> dict:
    """Ingest MarineCadastre AIS CSV."""
    df = pd.read_csv(file_path, low_memory=False)
    
    col_map = {str(c).lower(): c for c in df.columns}
    
    def get_col(name):
        return col_map.get(name.lower())
    
    mmsi_col = get_col('MMSI')
    dt_col = get_col('BaseDateTime')
    lat_col = get_col('LAT')
    lon_col = get_col('LON')
    sog_col = get_col('SOG')
    cog_col = get_col('COG')
    head_col = get_col('Heading')
    name_col = get_col('VesselName')
    type_col = get_col('VesselType')
    status_col = get_col('Status')
    len_col = get_col('Length')
    wid_col = get_col('Width')
    
    if not all([mmsi_col, dt_col, lat_col, lon_col]):
        return {"vessels_created": 0, "records_created": 0, "errors": 1}
    
    df = df.dropna(subset=[mmsi_col, dt_col, lat_col, lon_col])
    
    df[lat_col] = df[lat_col].clip(lower=-90, upper=90)
    df[lon_col] = df[lon_col].clip(lower=-180, upper=180)
    
    df['parsed_dt'] = pd.to_datetime(df[dt_col], errors='coerce')
    df = df.dropna(subset=['parsed_dt'])
    if df['parsed_dt'].dt.tz is None:
        df['parsed_dt'] = df['parsed_dt'].dt.tz_localize('UTC')
    
    df = df.replace({np.nan: None})
    
    vessels_created = 0
    records_created = 0
    errors = 0
    
    vessel_cache = {}
    vessel_data = df.groupby(mmsi_col).last()
    
    for mmsi, row in vessel_data.iterrows():
        try:
            mmsi_str = str(mmsi)[:9]
            v, created = Vessel.objects.get_or_create(
                mmsi=mmsi_str,
                defaults={
                    'name': str(row[name_col]) if name_col and row[name_col] else '',
                    'vessel_type': str(row[type_col]) if type_col and row[type_col] else '',
                    'length_m': float(row[len_col]) if len_col and row[len_col] is not None else None,
                    'width_m': float(row[wid_col]) if wid_col and row[wid_col] is not None else None,
                }
            )
            vessel_cache[mmsi_str] = v
            if created:
                vessels_created += 1
        except Exception:
            errors += 1
            
    ais_records = []
    
    for _, row in df.iterrows():
        try:
            mmsi_str = str(row[mmsi_col])[:9]
            vessel = vessel_cache.get(mmsi_str)
            if not vessel:
                continue
                
            ais_records.append(AISRecord(
                vessel=vessel,
                timestamp=row['parsed_dt'],
                lat=row[lat_col],
                lon=row[lon_col],
                speed_knots=float(row[sog_col]) if sog_col and row[sog_col] is not None else None,
                course=float(row[cog_col]) if cog_col and row[cog_col] is not None else None,
                heading=float(row[head_col]) if head_col and row[head_col] is not None else None,
                status=str(row[status_col]) if status_col and row[status_col] else ''
            ))
            
            if len(ais_records) >= batch_size:
                AISRecord.objects.bulk_create(ais_records)
                records_created += len(ais_records)
                ais_records = []
        except Exception:
            errors += 1
            
    if ais_records:
        AISRecord.objects.bulk_create(ais_records)
        records_created += len(ais_records)
        
    return {
        "vessels_created": vessels_created,
        "records_created": records_created,
        "errors": errors
    }
