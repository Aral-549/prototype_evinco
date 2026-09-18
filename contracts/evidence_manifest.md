# Contract: Forensic Chain of Custody (`apps/pipeline/evidence.py`)

## Purpose
Produce a tamper-evident, reproducible record of exactly what was analysed, by which model,
against which met-ocean data, under which parameters and random seed — so that a third party
(Indian Coast Guard, DG Shipping, a court) can re-run the analysis and obtain an identical
result, or prove that a submitted dossier was altered.

## Inputs
- `image_path`: str, path to the exact bytes analysed
- `model_info`: dict from `ModelManager.get_model_info()`
- `checkpoint_path`: str
- `parameters`: dict of every run parameter that affects the result (seed, thresholds,
  radii, windage, durations)
- `metocean_records`: list of `{lat, lon, time, source, fetched_at, values}`
- `stage_digests`: dict mapping pipeline stage name to the digest of that stage's output

## Outputs
- `EvidenceManifest` dataclass, serialisable to canonical JSON (sorted keys, no whitespace
  variance, UTC ISO-8601 timestamps) with:
  - `manifest_version`: str
  - `input_sha256`: str, 64 lowercase hex chars — digest of the image file bytes
  - `model_sha256`, `model_name`, `model_version`
  - `code_version`: str, git commit of the analysing code, or `"unavailable"`
  - `parameters`, `metocean_provenance`, `stage_digests`
  - `created_at`: UTC ISO-8601
  - `manifest_sha256`: digest of the canonical JSON of all the above fields

## Behavior cases (input → expected output)
| # | Input | Expected output | Notes |
|---|-------|------------------|-------|
| 1 | Same image, model, parameters, seed, met-ocean records | Identical `manifest_sha256` across runs and across machines | The core reproducibility claim |
| 2 | One byte of the image changed | `input_sha256` and `manifest_sha256` both change | Tamper evidence |
| 3 | Any single parameter changed | `manifest_sha256` changes | Parameters are part of the evidence |
| 4 | `created_at` differs between two runs, all else equal | `manifest_sha256` still differs | Timestamp is inside the digest by design; `verify()` compares the content digest instead |
| 5 | `verify(manifest, image_path)` with the original image | returns `(True, [])` | Verification path |
| 6 | `verify(manifest, other_image)` | returns `(False, [reason])` naming the mismatched field | Actionable failure |
| 7 | Missing checkpoint file | `model_sha256` is `"unavailable"`; manifest still builds | Must never crash the pipeline |
| 8 | Dict key insertion order differs between runs | `manifest_sha256` unchanged | Canonicalisation, not accidental ordering |

## Edge cases that must be covered
- Image file larger than RAM (digest must stream in chunks, not read whole)
- Checkpoint stored as a directory rather than a single file (digest over sorted file list)
- Non-ASCII vessel names or file paths in the manifest (UTF-8, `ensure_ascii=False` fixed)
- `float` values that differ only in representation (`1.0` vs `1`) must canonicalise identically

## Explicitly out of scope
- Cryptographic signing with an authority key (documented as the production next step;
  this contract covers integrity digests only, not non-repudiation)
- PDF dossier rendering

## Status
- [x] Drafted
- [ ] Reviewed by a human
- [ ] Implementation matches this contract
- [ ] Golden tests exist for every behavior case above
