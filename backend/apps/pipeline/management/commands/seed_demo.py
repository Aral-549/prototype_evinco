"""Seed two reproducible demo cases.

Creates one case that names a vessel and one that refuses to, so both halves of the
system's behaviour can be shown without hand-editing the database. Deterministic:
the same command always produces the same figures.

    python manage.py seed_demo            # both cases, clearing previous demo runs
    python manage.py seed_demo --keep     # add cases without clearing
"""
import os
import shutil
from datetime import datetime, timedelta, timezone

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ais.models import AISRecord, SuspectScore, Vessel
from apps.pipeline.models import PipelineRun
from apps.pipeline.orchestrator import run_pipeline

# The two cases are separated in time because attribution searches ALL vessels in
# the window around a release. Co-located demo fixtures would otherwise contaminate
# each other and both would report the same suspect.
CASES = [
    {
        'tag': 1,
        'label': 'positive attribution',
        # On the reconstructed release point, with a transponder blackout over it.
        'vessel_lat': 19.0540, 'vessel_lon': 71.8093,
    },
    {
        'tag': 2,
        'label': 'refusal (insufficient evidence)',
        # Present in the area, but ~25 km from the reconstructed release point.
        'vessel_lat': 19.2800, 'vessel_lon': 72.0500,
    },
]


class Command(BaseCommand):
    help = 'Seed reproducible demo cases (one attribution, one refusal).'

    def add_arguments(self, parser):
        parser.add_argument('--keep', action='store_true',
                            help='do not clear existing runs first')

    def handle(self, *args, **opts):
        scene = settings.CALIBRATION_DIR / 'synthetic_sar_calibration.png'
        if not scene.exists():
            self.stderr.write(self.style.ERROR(
                f'Calibration scene missing: {scene}\n'
                f'Run: python ai_model/calibration_data/make_calibration_scene.py'))
            return

        if not opts['keep']:
            PipelineRun.objects.all().delete()
            Vessel.objects.all().delete()
            self.stdout.write('Cleared existing runs and vessels.')

        uploads = os.path.join(settings.MEDIA_ROOT, 'uploads')
        os.makedirs(uploads, exist_ok=True)

        for case in CASES:
            self._seed(case, scene, uploads)

    def _seed(self, case, scene, uploads):
        tag = case['tag']
        rng = np.random.default_rng(7 + tag)

        dst = os.path.join(uploads, f'demo_case_{tag}.png')
        shutil.copy(str(scene), dst)

        # 30-day offset per case so the AIS search windows cannot overlap.
        offset = timedelta(days=30 * tag)
        detected_at = datetime(2026, 1, 15, 3, 30, tzinfo=timezone.utc) + offset
        release_at = datetime(2026, 1, 14, 4, 50, tzinfo=timezone.utc) + offset

        m1, m2 = f'41900{tag}234', f'56300{tag}876'
        AISRecord.objects.filter(vessel__mmsi__in=[m1, m2]).delete()
        Vessel.objects.filter(mmsi__in=[m1, m2]).delete()

        suspect = Vessel.objects.create(
            mmsi=m1, name='MV KAVERI STAR',
            vessel_type='Crude Oil Tanker', flag='India')
        bystander = Vessel.objects.create(
            mmsi=m2, name='MV SINGAPORE BELLE',
            vessel_type='Container', flag='Singapore')

        lat, lon = case['vessel_lat'], case['vessel_lon']
        for i in range(-18, 19):
            # A 90-minute transponder blackout across the release window.
            if -3 < i < 6:
                continue
            AISRecord.objects.create(
                vessel=suspect,
                timestamp=release_at + timedelta(minutes=10 * i),
                # Real GNSS fixes carry sub-metre jitter; an exact grid reads as
                # synthesised and trips the AIS integrity advisory.
                lat=lat + 0.002 * i + rng.normal(0, 3e-5),
                lon=lon + 0.002 * i + rng.normal(0, 3e-5),
                speed_knots=13.5 if i < 0 else 2.5,
            )
        for i in range(-18, 19):
            AISRecord.objects.create(
                vessel=bystander,
                timestamp=release_at + timedelta(minutes=10 * i),
                lat=20.5 + 0.01 * i + rng.normal(0, 3e-5),
                lon=73.5 + 0.01 * i + rng.normal(0, 3e-5),
                speed_knots=18.0,
            )

        run = PipelineRun.objects.create(
            image_path=dst, drift_duration_hours=24.0,
            bbox_min_lon=71.90, bbox_min_lat=18.90,
            bbox_max_lon=72.30, bbox_max_lat=19.30,
        )
        run_pipeline(run, dst, detection_time=detected_at)
        run.refresh_from_db()

        conclusion = (run.attribution_summary or {}).get('conclusion', 'n/a')
        audit = (run.robustness_report or {}).get('assessment', 'n/a')
        top = (SuspectScore.objects
               .filter(drift_result__spill_region__job=run.detection_job)
               .order_by('rank').first())

        self.stdout.write(self.style.SUCCESS(
            f"[{case['label']}] {run.id}"))
        self.stdout.write(
            f"    conclusion={conclusion}  audit={audit}  "
            f"regions={run.spills_detected} rejected={run.regions_rejected_as_lookalike}")
        if top:
            self.stdout.write(
                f"    top: {top.vessel.name} posterior={top.posterior:.3f} "
                f"cpa={top.cpa_km:.2f} km {top.anomalies_detected}")
