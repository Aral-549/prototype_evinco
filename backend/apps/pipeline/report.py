"""Forensic dossier PDF: the artefact that leaves the building.

The console is for investigating. This is what an officer files, emails, or hands to
a court, and it is written to be checked by someone who does not trust it.

Two rules shape the layout:

  - A number never appears without its uncertainty. A PDF that prints "73%" and
    leaves the robustness audit for a later page is misleading on paper in a way the
    web page is not: paper has no tooltips, and whoever reads page 1 may never reach
    page 2.
  - The limitations block is fixed and always present. It is not per-case, not
    editable, and not optional, because the failure mode for this kind of document is
    someone treating an indicative analysis as a finding of fact.
"""
import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

INK = colors.HexColor('#1a1d24')
MUTED = colors.HexColor('#5a6472')
RULE = colors.HexColor('#c8cdd6')
ACCENT = colors.HexColor('#b8801f')
ALERT = colors.HexColor('#b23b28')
OK = colors.HexColor('#2f7d52')

# Fixed, non-negotiable. Reproduced verbatim on every dossier.
LIMITATIONS = [
    "This is an indicative analysis produced to support investigation. It is not a "
    "finding of fact and does not by itself establish responsibility for pollution.",

    "The reconstructed release point is a probability distribution, not a location. "
    "The stated radii are where the ensemble placed the release; the true origin may "
    "lie outside them.",

    "Attribution is conditional on the assumptions listed under Robustness. Where that "
    "section reports the finding as contingent or fragile, the named vessel should be "
    "treated as a lead for further enquiry and nothing more.",

    "AIS is an unauthenticated broadcast. A vessel absent from this analysis may still "
    "be responsible, having transmitted nothing, been outside receiver coverage, or "
    "broadcast a false identity.",

    "Detection performance has been measured on synthetic imagery with known ground "
    "truth. It has not been validated against a labelled corpus of real Sentinel-1 "
    "scenes, and no figure in this document should be read as real-world accuracy.",

    "The system does not detect thin or weathered films: slicks with low contrast "
    "against the surrounding sea are missed entirely.",

    "The digests below establish integrity, not origin. They show this dossier is "
    "internally consistent with the data it names. They are not a signature and do "
    "not establish who produced it.",
]


def _styles():
    ss = getSampleStyleSheet()
    return {
        'h1': ParagraphStyle('h1', parent=ss['Heading1'], fontName='Helvetica-Bold',
                             fontSize=16, leading=19, textColor=INK, spaceAfter=2),
        'h2': ParagraphStyle('h2', parent=ss['Heading2'], fontName='Helvetica-Bold',
                             fontSize=10, leading=13, textColor=INK,
                             spaceBefore=10, spaceAfter=4),
        'body': ParagraphStyle('body', parent=ss['BodyText'], fontName='Helvetica',
                               fontSize=8.5, leading=12, textColor=INK,
                               alignment=TA_LEFT, spaceAfter=3),
        'muted': ParagraphStyle('muted', parent=ss['BodyText'], fontName='Helvetica',
                                fontSize=7.5, leading=10, textColor=MUTED, spaceAfter=2),
        'mono': ParagraphStyle('mono', parent=ss['BodyText'], fontName='Courier',
                               fontSize=7, leading=9.5, textColor=INK),
        'lead': ParagraphStyle('lead', parent=ss['BodyText'], fontName='Helvetica-Bold',
                               fontSize=11, leading=14, textColor=INK, spaceAfter=4),
    }


def _kv_table(rows, widths=(52 * mm, 122 * mm)):
    t = Table([[Paragraph(f'<b>{k}</b>', _styles()['body']),
                Paragraph(str(v), _styles()['body'])] for k, v in rows],
              colWidths=widths)
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -2), 0.25, RULE),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))
    return t


def _pct(v, digits=0):
    return '—' if v is None else f'{v * 100:.{digits}f}%'


def _num(v, digits=2, suffix=''):
    return '—' if v is None else f'{v:.{digits}f}{suffix}'


def build_pdf(dossier: dict) -> bytes:
    """Render a dossier dict to PDF bytes."""
    S = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"MarSlick case {dossier['run']['id'][:8]}",
        author='MarSlick',
    )

    run = dossier['run']
    model = dossier.get('model', {})
    attribution = dossier.get('attribution', {}) or {}
    summary = attribution.get('summary', {}) or {}
    robustness = dossier.get('robustness', {}) or {}
    coc = dossier.get('chain_of_custody', {}) or {}
    regions = dossier.get('regions', []) or []
    suspects = dossier.get('suspects', []) or []

    conclusion = summary.get('conclusion') or 'no conclusion recorded'
    story = []

    # ── Header ────────────────────────────────────────────────
    story.append(Paragraph('MARITIME POLLUTION — FORENSIC DOSSIER', S['h1']))
    story.append(Paragraph(
        'Automated SAR detection, drift reconstruction and AIS attribution. '
        'Indicative analysis for investigative triage.', S['muted']))
    story.append(Spacer(1, 5))
    story.append(_kv_table([
        ('Case reference', f"<font face='Courier'>{run['id']}</font>"),
        ('Issued', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')),
        ('Analysis completed', (run.get('completed_at') or '—')[:19].replace('T', ' ')),
        ('Status', f"{run.get('status')} / {run.get('stage')}"),
        ('Conclusion', f"<b>{conclusion.replace('_', ' ').upper()}</b>"),
    ]))

    # ── 1. Finding ────────────────────────────────────────────
    story.append(Paragraph('1. FINDING', S['h2']))
    if summary.get('headline'):
        story.append(Paragraph(summary['headline'], S['lead']))
    else:
        story.append(Paragraph('No attribution conclusion was recorded for this run.',
                               S['body']))

    unknown = attribution.get('unknown_vessel_posterior')
    top = suspects[0] if suspects else None
    named = top and conclusion not in ('insufficient_evidence', 'insufficient')

    finding_rows = []
    if named:
        finding_rows.append(('Most probable source',
                             f"{top['vessel_name'] or 'Unnamed'} "
                             f"(MMSI {top['mmsi']}) — {_pct(top.get('posterior'), 1)}"))
    # The alternative hypothesis is printed with the suspect, never separately.
    finding_rows.append(('Probability the source is absent from this AIS data',
                         _pct(unknown, 1)))
    if run.get('regions_rejected_as_lookalike'):
        finding_rows.append(('Candidate regions rejected as look-alikes',
                             str(run['regions_rejected_as_lookalike'])))
    story.append(Spacer(1, 3))
    story.append(_kv_table(finding_rows))

    # ── 2. Robustness — on the same page as the finding ───────
    story.append(Paragraph('2. ROBUSTNESS OF THIS FINDING', S['h2']))
    if robustness.get('error') or not robustness.get('scenarios_run'):
        story.append(Paragraph('No robustness audit was recorded for this run.', S['body']))
    else:
        assessment = (robustness.get('assessment') or 'unknown').upper()
        colour = {'ROBUST': OK, 'CONDITIONAL': ACCENT, 'FRAGILE': ALERT}.get(assessment, MUTED)
        story.append(Paragraph(
            f"<font color='#{colour.hexval()[2:]}'><b>{assessment}</b></font> — the "
            f"conclusion held in <b>{_pct(robustness.get('stability'))}</b> of "
            f"{robustness.get('scenarios_run')} alternative assumption sets, each drawn "
            f"from ranges a domain expert would accept.", S['body']))
        for line in (robustness.get('narrative') or [])[1:]:
            story.append(Paragraph(f'• {line}', S['body']))

        bps = robustness.get('breaking_points') or []
        if bps:
            story.append(Spacer(1, 3))
            story.append(Paragraph('<b>Breaking points</b> — the smallest defensible '
                                   'changes that flip the leading candidate:', S['body']))
            for bp in bps:
                story.append(Paragraph(
                    f"• [{bp.get('value')}] {bp.get('note')} "
                    f"Leading candidate becomes {bp.get('new_top')}.", S['muted']))

    # ── 3. Detection ──────────────────────────────────────────
    story.append(Paragraph('3. DETECTION', S['h2']))
    if not regions:
        story.append(Paragraph('No oil-like regions were retained for this scene.', S['body']))
    for r in regions:
        vol = r.get('volume_estimate') or {}
        story.append(_kv_table([
            ('Surface area', _num(r.get('area_sq_km'), 2, ' km²')),
            ('Probability this is mineral oil', _pct(r.get('oil_probability'), 1)),
            ('Look-alike screening', (r.get('lookalike_verdict') or '—').replace('_', ' ')),
            ('Estimated volume',
             f"{_num(vol.get('volume_m3_min'), 1)} – {_num(vol.get('volume_m3_max'), 1)} m³"
             if vol.get('volume_m3_max') is not None else '—'),
        ]))
        if vol.get('caveat'):
            story.append(Paragraph(vol['caveat'], S['muted']))

    # ── 4. Drift ──────────────────────────────────────────────
    drift = regions[0].get('drift') if regions else None
    if drift:
        story.append(Paragraph('4. RECONSTRUCTED RELEASE', S['h2']))
        story.append(_kv_table([
            ('Position', f"{_num(drift.get('origin_lat'), 4)}, "
                         f"{_num(drift.get('origin_lon'), 4)}"),
            ('Time', (drift.get('origin_time') or '—')[:19].replace('T', ' ') + ' UTC'),
            ('50% of release hypotheses within', _num(drift.get('radius_50_km'), 1, ' km')),
            ('90% of release hypotheses within', _num(drift.get('radius_90_km'), 1, ' km')),
            ('Ensemble', f"{drift.get('n_particles')} particles, seed "
                         f"{drift.get('ensemble_seed')}"),
            ('Met-ocean source', drift.get('metocean_source') or '—'),
            ('Estimated evaporation', _pct(drift.get('evaporated_fraction'))),
        ]))
        if drift.get('weathering_warning'):
            story.append(Paragraph(drift['weathering_warning'], S['muted']))
    elif run.get('stage') == 'georeference_gated':
        story.append(Paragraph('4. RECONSTRUCTED RELEASE', S['h2']))
        story.append(Paragraph(
            'Withheld. ' + (run.get('error_message') or
                            'The scene carried no geospatial anchor.'), S['body']))

    # ── 5. Candidates ─────────────────────────────────────────
    story.append(Paragraph('5. CANDIDATE VESSELS', S['h2']))
    if not suspects:
        story.append(Paragraph(
            'No AIS tracks were available in the window around the reconstructed '
            'release.', S['body']))
    else:
        head = ['#', 'MMSI', 'Vessel', 'Posterior', 'CPA', 'Verdict', 'Flags']
        data = [[Paragraph(f'<b>{h}</b>', S['muted']) for h in head]]
        for s in suspects:
            flags = list(s.get('anomalies') or [])
            if not s.get('integrity_plausible', True):
                flags.append('TRACK NOT PHYSICALLY CONSISTENT')
            data.append([
                Paragraph(str(s.get('rank')), S['muted']),
                Paragraph(f"<font face='Courier'>{s.get('mmsi')}</font>", S['muted']),
                Paragraph(s.get('vessel_name') or 'Unnamed', S['muted']),
                Paragraph(_pct(s.get('posterior'), 1), S['muted']),
                Paragraph(_num(s.get('cpa_km'), 2, ' km'), S['muted']),
                Paragraph(s.get('verdict') or '—', S['muted']),
                Paragraph(', '.join(f.replace('_', ' ') for f in flags) or '—', S['muted']),
            ])
        t = Table(data, colWidths=[7 * mm, 22 * mm, 40 * mm, 20 * mm, 18 * mm,
                                   22 * mm, 45 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, 0), (-1, 0), 0.6, INK),
            ('LINEBELOW', (0, 1), (-1, -1), 0.25, RULE),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(t)

        for s in suspects:
            material = [f for f in (s.get('integrity_flags') or [])
                        if f.get('severity', 0) >= 0.5]
            if material:
                story.append(Spacer(1, 3))
                story.append(Paragraph(
                    f"<b>AIS integrity — MMSI {s.get('mmsi')}</b>", S['body']))
                for f in material:
                    story.append(Paragraph(f"• {f.get('detail')}", S['muted']))

    # ── 6. Chain of custody ───────────────────────────────────
    story.append(Spacer(1, 4))
    story.append(Paragraph('6. CHAIN OF CUSTODY', S['h2']))
    story.append(Paragraph(
        'Digests over the exact inputs, weights and parameters used. Re-running this '
        'case with the same seed reproduces these values; any alteration changes them.',
        S['muted']))
    story.append(Spacer(1, 3))

    members = model.get('ensemble_members') or []
    story.append(_kv_table([
        ('Input scene SHA-256', f"<font face='Courier'>{coc.get('input_sha256', 'unavailable')}</font>"),
        ('Model weights SHA-256', f"<font face='Courier'>{coc.get('model_sha256', 'unavailable')}</font>"),
        ('Content SHA-256', f"<font face='Courier'>{coc.get('content_sha256', 'unavailable')}</font>"),
        ('Manifest SHA-256', f"<font face='Courier'>{coc.get('manifest_sha256', 'unavailable')}</font>"),
        ('Model', ' + '.join(members) if members else (model.get('name') or '—')),
        ('Model version', model.get('version') or '—'),
        ('Code commit', f"<font face='Courier'>{coc.get('code_version', 'unavailable')}</font>"),
        ('Manifest issued', (coc.get('created_at') or '—')[:19].replace('T', ' ')),
        ('Scene submitted by', run.get('submitted_by') or 'anonymous'),
    ]))

    # ── 7. Limitations ────────────────────────────────────────
    story.append(Paragraph('7. LIMITATIONS AND SCOPE', S['h2']))
    for item in LIMITATIONS:
        story.append(Paragraph(f'• {item}', S['body']))

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont('Helvetica', 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm,
                          f"MarSlick case {run['id']}  ·  indicative analysis, not a finding of fact")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f'page {doc_.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
