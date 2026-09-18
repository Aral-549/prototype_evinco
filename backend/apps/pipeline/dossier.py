"""Consolidated dossier endpoint: everything one case needs in a single payload.

The results view previously assembled a partial picture for a server-rendered
template and omitted every field added by the look-alike, ensemble, attribution and
chain-of-custody stages. A separate SPA would otherwise need four or five round
trips and still not see the evidence record.
"""
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ais.models import SuspectScore
from apps.drift.models import DriftResult

from .models import PipelineRun


def build_dossier(run: PipelineRun) -> dict:
    """Assemble the full evidentiary picture for one pipeline run."""
    from apps.detection.inference import ModelManager

    try:
        model_info = ModelManager().get_model_info()
    except Exception as exc:
        model_info = {'error': str(exc)}

    payload = {
        'run': {
            'id': str(run.id),
            'status': run.status,
            'stage': run.stage,
            'stage_durations_ms': run.stage_durations,
            'created_at': run.created_at.isoformat() if run.created_at else None,
            'completed_at': run.completed_at.isoformat() if run.completed_at else None,
            'is_georeferenced': run.is_georeferenced,
            'error_message': run.error_message,
            'spills_detected': run.spills_detected,
            'suspects_ranked': run.suspects_ranked,
            'regions_rejected_as_lookalike': run.regions_rejected_as_lookalike,
            'metocean_source': run.metocean_source,
            'drift_duration_hours': run.drift_duration_hours,
            'total_duration_ms': sum((run.stage_durations or {}).values()),
            'submitted_by': run.submitted_by or 'anonymous',
        },
        'model': {
            'name': model_info.get('name'),
            'version': model_info.get('version'),
            'checkpoint_id': model_info.get('checkpoint_id'),
            'dice_score': model_info.get('dice_score'),
            'iou_score': model_info.get('iou_score'),
            'output_activation': model_info.get('output_activation'),
            'is_fallback': model_info.get('is_fallback', False),
            'ensemble_members': model_info.get('ensemble_members') or [],
            'ensemble_size': model_info.get('ensemble_size') or 1,
        },
        'attribution': {
            'summary': run.attribution_summary or {},
            'unknown_vessel_posterior': run.unknown_vessel_posterior,
        },
        'chain_of_custody': run.evidence_manifest or {},
        'robustness': run.robustness_report or {},
        'regions': [],
        'suspects': [],
    }

    if not run.detection_job:
        return payload

    job = run.detection_job
    payload['imagery'] = {
        'uploaded_image': job.uploaded_image.url if job.uploaded_image else None,
        'result_mask': job.result_mask.url if job.result_mask else None,
        'probability_map': f'/media/results/{run.id}_probability.png',
        'width': job.image_width,
        'height': job.image_height,
        'processing_time_ms': job.processing_time_ms,
    }

    regions = list(job.spill_regions.all())
    drifts = {d.spill_region_id: d for d in
              DriftResult.objects.filter(spill_region__in=regions)}

    for region in regions:
        drift = drifts.get(region.id)
        entry = {
            'id': region.id,
            'polygon_geojson': region.polygon_geojson,
            'centroid_lat': region.centroid_lat,
            'centroid_lon': region.centroid_lon,
            'area_sq_km': region.area_sq_km,
            'confidence': region.confidence,
            'oil_probability': region.oil_probability,
            'lookalike_verdict': region.lookalike_verdict,
            'lookalike_features': region.lookalike_features,
            'lookalike_contributions': region.lookalike_contributions,
            'lookalike_notes': region.lookalike_notes,
            'shape_complexity': region.shape_complexity,
            'volume_estimate': region.volume_estimate,
            'drift': None,
        }
        if drift:
            entry['drift'] = {
                'id': drift.id,
                'engine_used': drift.engine_used,
                'origin_lat': drift.origin_lat,
                'origin_lon': drift.origin_lon,
                'origin_time': drift.origin_time.isoformat() if drift.origin_time else None,
                'origin_uncertainty_km': drift.origin_uncertainty_km,
                'radius_50_km': drift.radius_50_km,
                'radius_90_km': drift.radius_90_km,
                'confidence_polygon_50': drift.confidence_polygon_50,
                'confidence_polygon_90': drift.confidence_polygon_90,
                # Particles are downsampled: 500 points is a heavy payload and the
                # map only needs enough to render a density cloud.
                'particles': (drift.origin_particles or [])[::max(
                    1, len(drift.origin_particles or [1]) // 200)],
                'n_particles': drift.n_particles,
                'ensemble_seed': drift.ensemble_seed,
                'hindcast_trajectory': drift.hindcast_trajectory,
                'forecast_trajectory': drift.forecast_trajectory,
                'evaporated_fraction': drift.evaporated_fraction,
                'weathering_warning': drift.weathering_warning,
                'metocean_source': drift.metocean_source,
                'metocean_degraded_steps': drift.metocean_degraded_steps,
                'wind_speed_mps': drift.wind_speed_mps,
                'wind_direction_deg': drift.wind_direction_deg,
                'current_speed_mps': drift.current_speed_mps,
                'current_direction_deg': drift.current_direction_deg,
                'duration_hours': drift.duration_hours,
            }
        payload['regions'].append(entry)

    suspects = (SuspectScore.objects
                .filter(drift_result__spill_region__in=regions)
                .select_related('vessel')
                .order_by('rank'))

    # Track window around the release, so the map can draw where each suspect
    # actually was rather than just a single closest-approach marker.
    from datetime import timedelta
    from apps.ais.models import AISRecord

    origin_times = [d.origin_time for d in drifts.values() if d.origin_time]
    track_lo = min(origin_times) - timedelta(hours=12) if origin_times else None
    track_hi = max(origin_times) + timedelta(hours=12) if origin_times else None

    tracks_by_mmsi = {}
    if track_lo and suspects:
        mmsis = [s.vessel_id for s in suspects]
        for rec in (AISRecord.objects
                    .filter(vessel_id__in=mmsis, timestamp__gte=track_lo,
                            timestamp__lte=track_hi)
                    .select_related('vessel')
                    .order_by('vessel_id', 'timestamp')):
            tracks_by_mmsi.setdefault(rec.vessel.mmsi, []).append({
                'lat': rec.lat, 'lon': rec.lon,
                'time': rec.timestamp.isoformat(),
                'speed_knots': rec.speed_knots,
            })

    for s in suspects:
        payload['suspects'].append({
            'track': tracks_by_mmsi.get(s.vessel.mmsi, []),
            'rank': s.rank,
            'mmsi': s.vessel.mmsi,
            'vessel_name': s.vessel.name,
            'vessel_type': s.vessel.vessel_type,
            'flag': s.vessel.flag,
            'posterior': s.posterior,
            'verdict': s.verdict,
            'spatiotemporal_likelihood': s.spatiotemporal_likelihood,
            'behavioural_factor': s.behavioural_factor,
            'cpa_km': s.cpa_km,
            'cpa_time': s.cpa_time.isoformat() if s.cpa_time else None,
            'anomalies': s.anomalies_detected,
            'explanation': s.explanation,
            # Legacy weighted ranking, kept so the two methods can be compared
            # side by side. Where they disagree, the disagreement is the finding.
            'legacy_composite_score': s.composite_score,
            'legacy_proximity_score': s.proximity_score,
            'legacy_temporal_score': s.temporal_score,
            'legacy_behavioral_score': s.behavioral_score,
            'integrity_plausible': s.integrity_plausible,
            'integrity_flags': s.integrity_flags,
            'max_implied_speed_kn': s.max_implied_speed_kn,
        })

    # The attribution summary is a snapshot taken at run time; the suspect rows are
    # live records. They can diverge if a vessel is later purged under a retention
    # policy or the AIS set is re-ingested, and the cascade takes its SuspectScore
    # rows with it. A dossier that asserts "strong -- MV X" above an empty candidate
    # table is worse than one that admits the supporting records are gone, so the
    # divergence is reported rather than rendered.
    summary = payload['attribution'].get('summary') or {}
    conclusion = summary.get('conclusion')
    if conclusion and conclusion != 'insufficient_evidence' and not payload['suspects']:
        payload['attribution']['stale'] = True
        payload['attribution']['stale_reason'] = (
            'This run concluded with a named vessel, but the AIS records supporting '
            'that conclusion are no longer in the database. The finding below is the '
            'snapshot taken at run time and cannot currently be re-derived.'
        )

    return payload


class PipelineDossierView(APIView):
    """GET: the complete evidentiary dossier for one run, in one request."""

    def get(self, request, pk):
        run = get_object_or_404(PipelineRun, pk=pk)
        return Response(build_dossier(run))


class PipelineStatusView(APIView):
    """GET: lightweight status, for the stepper to poll without pulling the dossier."""

    def get(self, request, pk):
        run = get_object_or_404(PipelineRun, pk=pk)
        return Response({
            'id': str(run.id),
            'status': run.status,
            'stage': run.stage,
            'stage_durations_ms': run.stage_durations,
            'spills_detected': run.spills_detected,
            'suspects_ranked': run.suspects_ranked,
            'regions_rejected_as_lookalike': run.regions_rejected_as_lookalike,
            'error_message': run.error_message,
            'is_georeferenced': run.is_georeferenced,
        })


class PipelineRunListView(APIView):
    """GET: recent runs, for the case list."""

    def get(self, request):
        limit = min(int(request.query_params.get('limit', 20)), 100)
        runs = PipelineRun.objects.all()[:limit]
        return Response([{
            'id': str(r.id),
            'status': r.status,
            'stage': r.stage,
            'created_at': r.created_at.isoformat() if r.created_at else None,
            'spills_detected': r.spills_detected,
            'suspects_ranked': r.suspects_ranked,
            'is_georeferenced': r.is_georeferenced,
            'conclusion': (r.attribution_summary or {}).get('conclusion'),
            'manifest_sha256': r.manifest_sha256,
        } for r in runs])


class PipelineReportPDFView(APIView):
    """GET: the case as a filable PDF dossier."""

    def get(self, request, pk):
        from .report import build_pdf

        run = get_object_or_404(PipelineRun, pk=pk)
        pdf = build_pdf(build_dossier(run))

        response = HttpResponse(pdf, content_type='application/pdf')
        # `inline` so a reviewer sees it in the browser; the console's download
        # button supplies its own filename.
        response['Content-Disposition'] = (
            f'inline; filename="marslick-case-{str(run.id)[:8]}.pdf"')
        response['Content-Length'] = str(len(pdf))
        return response
