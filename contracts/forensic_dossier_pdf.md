# Contract: Forensic Dossier PDF (`apps/pipeline/report.py`)

## Purpose
Render one analysis run as a self-contained PDF an enforcement officer can file,
email, or hand to a court. The web console is for investigating; this is the artefact
that leaves the building.

Its job is not to look impressive. It is to be **checkable by someone who does not
trust it**: every number carries its uncertainty, every conclusion carries the
assumptions it rests on, and the integrity digests are printed so a recipient can
verify the dossier was not altered after issue.

## Inputs
- `run`: a `PipelineRun` (completed, failed, or georeference-gated)
- `dossier`: the dict from `apps.pipeline.dossier.build_dossier`

## Outputs
- `bytes` of a PDF, or a streamed `HttpResponse` from the view
- Filename: `marslick-case-<first 8 of run id>.pdf`

## Required content, in order
1. **Header** — case id, issue timestamp (UTC), and the conclusion band
2. **Finding** — the headline sentence, the named vessel's posterior, and the
   unknown-vessel probability, stated together and never separately
3. **Robustness** — stability, assessment, and the breaking points. A PDF that prints
   "73%" without printing "survives 19% of assumption sets" is misleading on paper in
   a way the web page is not, because paper has no tooltips.
4. **Detection** — area, oil probability, look-alike verdict, volume band with its caveat
5. **Drift** — reconstructed release point and time, 50%/90% radii, met-ocean source
6. **Candidates** — ranked table: rank, MMSI, name, posterior, CPA, verdict, anomalies
7. **Chain of custody** — all four digests in full (not truncated), model name and
   version, code commit
8. **Limitations** — a fixed, non-negotiable block listing what the system cannot do

## Behavior cases (input → expected output)
| # | Input | Expected output | Notes |
|---|-------|------------------|-------|
| 1 | Completed run, strong attribution | PDF containing the vessel name, its posterior, AND the unknown-vessel posterior | Never print a suspect without the alternative |
| 2 | Run concluding `insufficient_evidence` | PDF states no vessel could be placed; the candidate table is present but no vessel is described as the source | Must not read as an accusation |
| 3 | Run whose audit says `fragile` | The fragility and its breaking points appear on the SAME page as the finding | Burying it later is how a caveat gets lost |
| 4 | Georeference-gated run | PDF renders, explains the gate, omits drift and attribution sections | A partial result is still a record |
| 5 | Failed run | PDF renders with the error and no fabricated findings | |
| 6 | Any run | Digests printed in full, 64 hex chars, not truncated | A truncated hash cannot be verified |
| 7 | Any run | The limitations block is present and identical every time | It is not optional and not editable per-case |
| 8 | Run with a suspect whose AIS track is implausible | The integrity flags appear next to that vessel | An unreliable track must not look clean on paper |

## Edge cases that must be covered
- A run with no detected regions
- A vessel name containing non-ASCII characters
- A very long list of candidates (table must paginate, not overflow)
- `robustness_report` absent or carrying an `error` key
- Missing chain-of-custody manifest (print "unavailable", never omit the section)

## Explicitly out of scope
- Cryptographic signing. The PDF carries integrity digests, not a signature, and the
  limitations block says so. Non-repudiation needs an authority-held key.
- Embedding the map image (the web console remains the interactive view)

## Status
- [x] Drafted
- [ ] Reviewed by a human
- [ ] Implementation matches this contract
- [ ] Golden tests exist for every behavior case above
