"""End-to-end forensic pipeline with structured stage-boundary logging.

Stage boundaries (each logged with its input summary, output summary and duration):

    upload -> [1] detection -> [2] look-alike screening -> [3] drift ensemble
           -> [4] AIS attribution -> [5] evidence manifest -> dossier

Three safeguard layers gate the flow:

    Layer 1  SAR out-of-distribution check   (preprocessing.validate_sar_characteristics)
    Layer 2  Oil vs look-alike discrimination (detection.lookalike)
    Layer 3  Georeference gate               (no coordinates -> no attribution)
"""
import logging
import os
import time

import cv2
import numpy as np
from django.conf import settings
from django.utils import timezone

from apps.detection.inference import ModelManager
from apps.detection.preprocessing import load_image
from apps.detection.postprocessing import mask_to_polygons, pixels_to_geo
from apps.detection.lookalike import assess_regions
from apps.drift.engines.ensemble import EnsembleDriftEngine, EnsembleDriftInput
from apps.drift.metocean import fetch_metocean_vectors, make_timeseries_provider
from apps.ais.attribution import attribute, summarise
from apps.ais.robustness import audit_conclusion, check_track_integrity
from apps.ais.scoring import score_vessels

from apps.detection.models import DetectionJob, SpillRegion
from apps.drift.models import DriftResult
from apps.ais.models import SuspectScore, AISRecord
from apps.pipeline.evidence import build_manifest, digest_stage_output

logger = logging.getLogger('pipeline')


def _log_stage(run_id, stage, inputs: dict, outputs: dict, duration_ms: int):
    """Structured log at a pipeline stage boundary.

    Deliberately structured rather than printed: when a result looks wrong, the
    question is always "which stage produced the bad value", and that is only
    answerable if every boundary recorded what went in and what came out.
    """
    logger.info(
        f'stage_complete stage={stage} run={run_id}',
        extra={
            'stage': stage,
            'duration_ms': duration_ms,
            'correlation_id': str(run_id),
            'stage_inputs': inputs,
            'stage_outputs': outputs,
        },
    )


def run_pipeline(pipeline_run, image_path: str, detection_time=None, user_bbox=None) -> None:
    metocean_records = []
    stage_digests = {}

    try:
        if detection_time is None:
            detection_time = timezone.now()

        if user_bbox is None and all(
            getattr(pipeline_run, k) is not None
            for k in ('bbox_min_lon', 'bbox_min_lat', 'bbox_max_lon', 'bbox_max_lat')
        ):
            user_bbox = (pipeline_run.bbox_min_lon, pipeline_run.bbox_min_lat,
                         pipeline_run.bbox_max_lon, pipeline_run.bbox_max_lat)

        # ══ Stage 1: Detection (Layer 1 SAR OOD gate runs inside load_image) ══
        pipeline_run.status = 'detecting'
        pipeline_run.stage = 'detection'
        pipeline_run.save()

        t0 = time.time()
        image_array, metadata = load_image(image_path, user_bbox=user_bbox)
        h, w = metadata['height'], metadata['width']
        is_georeferenced = metadata.get('is_georeferenced', False)
        bbox = metadata.get('bbox')

        pipeline_run.is_georeferenced = is_georeferenced
        pipeline_run.save(update_fields=['is_georeferenced'])

        rel_image_path = os.path.relpath(image_path, settings.MEDIA_ROOT)
        detection_job = DetectionJob.objects.create(
            uploaded_image=rel_image_path, image_width=w, image_height=h,
            status='processing',
        )
        pipeline_run.detection_job = detection_job
        pipeline_run.save()

        model = ModelManager()
        prob_map, uncertainty_map = model.predict_proba(image_array)
        threshold = float(model.get_model_info().get(
            'threshold', getattr(settings, 'UNET_THRESHOLD', 0.5)))
        mask = (prob_map > threshold).astype(np.uint8) * 255
        elapsed_ms = int((time.time() - t0) * 1000)

        results_dir = os.path.join(settings.MEDIA_ROOT, 'results')
        os.makedirs(results_dir, exist_ok=True)
        mask_filename = f'{pipeline_run.id}_mask.png'
        cv2.imwrite(os.path.join(results_dir, mask_filename), mask)
        # The continuous posterior is kept too: a binary mask discards exactly the
        # information an operator needs to triage a marginal detection.
        prob_filename = f'{pipeline_run.id}_probability.png'
        cv2.imwrite(os.path.join(results_dir, prob_filename),
                    (prob_map * 255).astype(np.uint8))

        detection_job.result_mask = f'results/{mask_filename}'
        detection_job.processing_time_ms = elapsed_ms
        detection_job.status = 'completed'
        detection_job.save()

        raw_polygons = mask_to_polygons(mask, prob_map=prob_map)
        geo_polygons = pixels_to_geo(raw_polygons, w, h, bbox=bbox)

        _log_stage(pipeline_run.id, 'detection',
                   {'image': os.path.basename(image_path), 'width': w, 'height': h,
                    'georeferenced': is_georeferenced},
                   {'regions': len(raw_polygons),
                    'mean_posterior': round(float(prob_map.mean()), 4),
                    'max_posterior': round(float(prob_map.max()), 4)},
                   elapsed_ms)
        stage_digests['detection'] = digest_stage_output(
            [{'centroid': p['centroid'], 'area_px': p['area_pixels'],
              'conf': p['confidence']} for p in raw_polygons])

        # ══ Stage 2: Layer 2 look-alike screening ══════════════════
        t_look = time.time()
        # Wind at the scene decides whether a dark patch can be oil at all.
        scene_wind = None
        if is_georeferenced and geo_polygons:
            first = geo_polygons[0]
            if first.get('centroid_lat') is not None:
                met = fetch_metocean_vectors(
                    first['centroid_lat'], first['centroid_lon'], detection_time)
                scene_wind = met.get('wind_speed_mps')
                metocean_records.append({
                    'lat': first['centroid_lat'], 'lon': first['centroid_lon'],
                    'time': detection_time.isoformat(), 'source': met.get('source'),
                    'fetched_at': timezone.now().isoformat(), 'values': met,
                })

        gray = image_array[:, :, 0].astype(np.float32) / 255.0
        assessments = assess_regions(gray, raw_polygons, prob_map=prob_map,
                                     wind_speed_mps=scene_wind)

        reject_below = float(getattr(settings, 'LOOKALIKE_REJECT_BELOW', 0.35))
        spill_regions, rejected = [], 0

        for gp, assessment in zip(geo_polygons, assessments):
            if assessment.oil_probability < reject_below:
                rejected += 1
                logger.info(
                    f'Region rejected as look-alike (p_oil='
                    f'{assessment.oil_probability:.3f}): {assessment.notes}',
                    extra={'stage': 'lookalike', 'correlation_id': str(pipeline_run.id)},
                )
                continue

            region = SpillRegion.objects.create(
                job=detection_job,
                polygon_geojson=gp['polygon_geojson'],
                centroid_lat=gp['centroid_lat'],
                centroid_lon=gp['centroid_lon'],
                area_sq_km=gp.get('area_sq_km'),
                confidence=gp.get('confidence', 0.0),
                oil_probability=assessment.oil_probability,
                lookalike_verdict=assessment.verdict,
                lookalike_features=assessment.features,
                lookalike_contributions=assessment.contributions,
                lookalike_notes=assessment.notes,
                volume_estimate=gp.get('volume_estimate', {}),
                shape_complexity=gp.get('shape_complexity'),
            )
            spill_regions.append(region)

        pipeline_run.spills_detected = len(spill_regions)
        pipeline_run.regions_rejected_as_lookalike = rejected
        pipeline_run.stage_durations['detection'] = elapsed_ms
        pipeline_run.stage_durations['lookalike'] = int((time.time() - t_look) * 1000)

        _log_stage(pipeline_run.id, 'lookalike',
                   {'candidates': len(geo_polygons), 'scene_wind_mps': scene_wind},
                   {'accepted': len(spill_regions), 'rejected_as_lookalike': rejected},
                   pipeline_run.stage_durations['lookalike'])
        stage_digests['lookalike'] = digest_stage_output(
            [a.to_dict() for a in assessments])

        # ══ Layer 3 gate: no coordinates, no attribution ═══════════
        if not is_georeferenced or any(r.centroid_lat is None for r in spill_regions):
            pipeline_run.status = 'completed'
            pipeline_run.stage = 'georeference_gated'
            pipeline_run.completed_at = timezone.now()
            pipeline_run.suspects_ranked = 0
            pipeline_run.error_message = (
                'Georeference Gate Active: Image lacks geospatial metadata (GeoTIFF tags or '
                'manual coordinates). Detection mask generated successfully, but hydrodynamic '
                'drift hindcasting and AIS vessel attribution are gated to prevent false '
                'maritime attribution.'
            )
            _finalise_manifest(pipeline_run, image_path, model, metocean_records,
                               stage_digests, detection_time)
            pipeline_run.save()
            return

        # ══ Stage 3: Monte Carlo drift ensemble ════════════════════
        pipeline_run.status = 'drifting'
        pipeline_run.stage = 'drift'
        pipeline_run.save()

        t_drift = time.time()
        engine = EnsembleDriftEngine()
        drift_results = []
        drift_inputs_by_region = {}
        met_source = 'default_fallback'

        defaults_untouched = (
            pipeline_run.wind_speed_mps == 5.0 and pipeline_run.wind_direction_deg == 180.0
            and pipeline_run.current_speed_mps == 0.3
            and pipeline_run.current_direction_deg == 90.0
        )

        for region in spill_regions:
            if defaults_untouched:
                met = fetch_metocean_vectors(
                    region.centroid_lat, region.centroid_lon, detection_time)
                wind_spd, wind_dir = met['wind_speed_mps'], met['wind_direction_deg']
                curr_spd, curr_dir = met['current_speed_mps'], met['current_direction_deg']
                met_source = met.get('source', 'default_fallback')
                # One batched hourly fetch for the whole window, not one call per
                # step: the per-step provider cost 24 round trips and ~34 s on a
                # 24 h hindcast, which by itself exceeded the 60 s end-to-end target.
                from datetime import timedelta as _td
                provider = make_timeseries_provider(
                    region.centroid_lat, region.centroid_lon,
                    detection_time - _td(hours=pipeline_run.drift_duration_hours + 2),
                    detection_time + _td(hours=2),
                    records=metocean_records, fallback=met)
            else:
                wind_spd = pipeline_run.wind_speed_mps
                wind_dir = pipeline_run.wind_direction_deg
                curr_spd = pipeline_run.current_speed_mps
                curr_dir = pipeline_run.current_direction_deg
                met_source = 'manual_override'
                # An explicit operator override is held constant on purpose: the
                # operator asserted these conditions, so silently replacing them
                # with API values mid-trajectory would discard their instruction.
                provider = None

            ensemble_input = EnsembleDriftInput(
                start_lat=region.centroid_lat,
                start_lon=region.centroid_lon,
                detection_time=detection_time,
                wind_speed_mps=wind_spd, wind_direction_deg=wind_dir,
                current_speed_mps=curr_spd, current_direction_deg=curr_dir,
                duration_hours=pipeline_run.drift_duration_hours,
                n_particles=int(getattr(settings, 'DRIFT_ENSEMBLE_PARTICLES', 500)),
                seed=int(getattr(settings, 'DRIFT_ENSEMBLE_SEED', 42)),
                metocean_provider=provider,
            )
            out = engine.compute(ensemble_input)
            drift_inputs_by_region[region.id] = ensemble_input

            drift_results.append(DriftResult.objects.create(
                spill_region=region, engine_used=engine.name,
                origin_lat=out.origin_lat, origin_lon=out.origin_lon,
                origin_time=out.origin_time,
                origin_uncertainty_km=out.origin_uncertainty_km,
                hindcast_trajectory=out.hindcast_trajectory,
                forecast_trajectory=out.forecast_trajectory,
                wind_speed_mps=wind_spd, wind_direction_deg=wind_dir,
                current_speed_mps=curr_spd, current_direction_deg=curr_dir,
                duration_hours=pipeline_run.drift_duration_hours,
                metocean_source=met_source,
                n_particles=out.n_particles, ensemble_seed=out.seed,
                radius_50_km=out.radius_50_km, radius_90_km=out.radius_90_km,
                confidence_polygon_50=out.confidence_polygon_50,
                confidence_polygon_90=out.confidence_polygon_90,
                origin_particles=out.particles,
                evaporated_fraction=out.evaporated_fraction,
                weathering_warning=out.weathering_warning,
                metocean_degraded_steps=out.metocean_degraded_steps,
            ))

        pipeline_run.metocean_source = met_source
        pipeline_run.stage_durations['drift'] = int((time.time() - t_drift) * 1000)
        _log_stage(pipeline_run.id, 'drift',
                   {'regions': len(spill_regions), 'metocean_source': met_source,
                    'duration_hours': pipeline_run.drift_duration_hours},
                   {'origins': [(round(d.origin_lat, 4), round(d.origin_lon, 4),
                                 round(d.radius_50_km or 0, 2)) for d in drift_results]},
                   pipeline_run.stage_durations['drift'])
        stage_digests['drift'] = digest_stage_output(
            [{'lat': d.origin_lat, 'lon': d.origin_lon, 'r50': d.radius_50_km,
              'time': d.origin_time} for d in drift_results])

        # ══ Stage 4: Bayesian AIS attribution ══════════════════════
        pipeline_run.status = 'scoring'
        pipeline_run.stage = 'ais_attribution'
        pipeline_run.save()

        t_ais = time.time()
        total_suspects = 0
        summary, unknown_posterior = {}, None

        for drift_res in drift_results:
            tracks = _load_tracks(drift_res)
            if not drift_res.origin_particles:
                continue

            results, unknown = attribute(
                particles=drift_res.origin_particles,
                tracks=tracks,
                capture_radius_km=float(getattr(
                    settings, 'ATTRIBUTION_CAPTURE_RADIUS_KM', 5.0)),
                prior_unknown=float(getattr(settings, 'ATTRIBUTION_PRIOR_UNKNOWN', 0.25)),
                origin_lat=drift_res.origin_lat, origin_lon=drift_res.origin_lon,
                origin_time=drift_res.origin_time,
            )

            # The legacy weighted scorer still runs, so its ranking can be shown
            # beside the Bayesian one. Where they disagree, the disagreement is
            # itself the interesting result.
            legacy = {s.vessel_id: s for s in score_vessels(drift_res)}

            integrity = {
                v.mmsi: check_track_integrity(v.mmsi, recs)
                for v, recs in tracks.items()
            }

            rows = []
            for res in results:
                old = legacy.get(res.vessel.id)
                integ = integrity.get(res.vessel.mmsi)
                rows.append(SuspectScore(
                    drift_result=drift_res, vessel=res.vessel,
                    proximity_score=old.proximity_score if old else 0.0,
                    temporal_score=old.temporal_score if old else 0.0,
                    behavioral_score=old.behavioral_score if old else 0.0,
                    composite_score=old.composite_score if old else 0.0,
                    min_distance_km=res.cpa_km if res.cpa_km is not None else 9999.0,
                    closest_time=res.cpa_time or drift_res.origin_time,
                    anomalies_detected=[a.code for a in res.anomalies],
                    rank=res.rank,
                    posterior=res.posterior,
                    spatiotemporal_likelihood=res.spatiotemporal_likelihood,
                    behavioural_factor=res.behavioural_factor,
                    cpa_km=res.cpa_km, cpa_time=res.cpa_time,
                    verdict=res.verdict, explanation=res.explanation,
                    integrity_plausible=integ.plausible if integ else True,
                    integrity_flags=[f for f in (integ.flags if integ else [])],
                    max_implied_speed_kn=integ.max_implied_speed_kn if integ else None,
                ))
            if rows:
                SuspectScore.objects.bulk_create(rows)
                total_suspects += len(rows)

            summary = summarise(results, unknown)
            unknown_posterior = unknown

        # ══ Stage 4b: adversarial self-audit ═══════════════════════
        # A posterior is conditional on assumptions nobody measured. Re-run the
        # attribution across their defensible ranges and report where it breaks,
        # so a fragile conclusion is never presented in the same voice as a robust
        # one. Cheap enough to run inline: ~0.5 s for 32 scenarios.
        t_audit = time.time()
        try:
            if drift_results and drift_inputs_by_region:
                primary = drift_results[0]
                audit_input = drift_inputs_by_region.get(primary.spill_region_id)
                if audit_input is not None:
                    top_mmsi = None
                    top_row = (SuspectScore.objects
                               .filter(drift_result=primary)
                               .select_related('vessel')
                               .order_by('rank').first())
                    if top_row and (top_row.posterior or 0) > (unknown_posterior or 0):
                        top_mmsi = top_row.vessel.mmsi

                    report = audit_conclusion(
                        audit_input,
                        _load_tracks(primary),
                        baseline_top_mmsi=top_mmsi,
                        n_scenarios=int(getattr(settings, 'ROBUSTNESS_SCENARIOS', 32)),
                        seed=int(getattr(settings, 'ROBUSTNESS_SEED', 7)),
                        base_capture_radius_km=float(getattr(
                            settings, 'ATTRIBUTION_CAPTURE_RADIUS_KM', 5.0)),
                        prior_unknown=float(getattr(
                            settings, 'ATTRIBUTION_PRIOR_UNKNOWN', 0.25)),
                    )
                    pipeline_run.robustness_report = report.to_dict()
                    stage_digests['robustness'] = digest_stage_output(report.to_dict())
        except Exception as exc:
            # The audit is a check ON the result, not part of producing it. Losing
            # it must not lose the analysis.
            logger.error(f'Robustness audit failed: {exc}')
            pipeline_run.robustness_report = {'error': str(exc)}

        pipeline_run.stage_durations['robustness'] = int((time.time() - t_audit) * 1000)
        _log_stage(pipeline_run.id, 'robustness', {'scenarios': getattr(
            settings, 'ROBUSTNESS_SCENARIOS', 32)},
            {'assessment': (pipeline_run.robustness_report or {}).get('assessment'),
             'stability': (pipeline_run.robustness_report or {}).get('stability')},
            pipeline_run.stage_durations['robustness'])

        pipeline_run.attribution_summary = summary
        pipeline_run.unknown_vessel_posterior = unknown_posterior
        pipeline_run.stage_durations['ais_attribution'] = int((time.time() - t_ais) * 1000)
        _log_stage(pipeline_run.id, 'ais_attribution',
                   {'drift_results': len(drift_results)},
                   {'suspects': total_suspects,
                    'conclusion': summary.get('conclusion'),
                    'unknown_posterior': unknown_posterior},
                   pipeline_run.stage_durations['ais_attribution'])
        stage_digests['ais_attribution'] = digest_stage_output(summary)

        # ══ Stage 5: Seal the chain of custody ═════════════════════
        _finalise_manifest(pipeline_run, image_path, model, metocean_records,
                           stage_digests, detection_time)

        pipeline_run.status = 'completed'
        pipeline_run.stage = 'completed'
        pipeline_run.completed_at = timezone.now()
        pipeline_run.suspects_ranked = total_suspects
        pipeline_run.save()

    except Exception as e:
        pipeline_run.status = 'failed'
        pipeline_run.stage = 'failed'
        pipeline_run.error_message = str(e)
        pipeline_run.save()
        logger.exception(f'Pipeline run {pipeline_run.id} failed: {e}',
                         extra={'correlation_id': str(pipeline_run.id), 'stage': 'failed'})
        raise


def _load_tracks(drift_res, window_hours: float = 48.0) -> dict:
    """AIS tracks in the window around the reconstructed release time."""
    from datetime import timedelta
    start = drift_res.origin_time - timedelta(hours=window_hours)
    end = drift_res.origin_time + timedelta(hours=window_hours)
    records = (AISRecord.objects
               .filter(timestamp__gte=start, timestamp__lte=end)
               .select_related('vessel')
               .order_by('vessel_id', 'timestamp'))
    tracks = {}
    for r in records:
        tracks.setdefault(r.vessel, []).append(r)
    return tracks


def _finalise_manifest(pipeline_run, image_path, model, metocean_records,
                       stage_digests, detection_time):
    """Build and attach the evidence manifest for this run."""
    try:
        info = model.get_model_info()
        manifest = build_manifest(
            image_path=image_path,
            model_info=info,
            checkpoint_path=str(model.active_checkpoint),
            parameters={
                'detection_time': detection_time,
                'threshold': info.get('threshold'),
                'input_size': info.get('input_size'),
                'stride': info.get('stride'),
                'normalization': info.get('normalization'),
                'output_activation': info.get('output_activation'),
                'tta': bool(getattr(settings, 'MODEL_TTA', False)),
                'lookalike_reject_below': getattr(settings, 'LOOKALIKE_REJECT_BELOW', 0.35),
                'drift_particles': getattr(settings, 'DRIFT_ENSEMBLE_PARTICLES', 500),
                'drift_seed': getattr(settings, 'DRIFT_ENSEMBLE_SEED', 42),
                'drift_duration_hours': pipeline_run.drift_duration_hours,
                'capture_radius_km': getattr(settings, 'ATTRIBUTION_CAPTURE_RADIUS_KM', 5.0),
                'prior_unknown': getattr(settings, 'ATTRIBUTION_PRIOR_UNKNOWN', 0.25),
                'bbox': [pipeline_run.bbox_min_lon, pipeline_run.bbox_min_lat,
                         pipeline_run.bbox_max_lon, pipeline_run.bbox_max_lat],
                # Part of the evidence: a dossier should say who submitted the scene
                # it is built from, and the digest is sealed so the attribution of
                # the submission cannot be edited after the fact.
                'submitted_by': pipeline_run.submitted_by or 'anonymous',
                'submitted_by_fingerprint': pipeline_run.submitted_by_fingerprint or '',
            },
            metocean_records=metocean_records,
            stage_digests=stage_digests,
        )
        pipeline_run.evidence_manifest = manifest.to_dict()
        pipeline_run.manifest_sha256 = manifest.manifest_sha256
    except Exception as exc:
        # A manifest failure must never destroy an otherwise valid analysis; it
        # degrades the result from "reproducible evidence" to "an indication",
        # and the dossier says so.
        logger.error(f'Could not build evidence manifest: {exc}')
        pipeline_run.evidence_manifest = {'error': str(exc)}
