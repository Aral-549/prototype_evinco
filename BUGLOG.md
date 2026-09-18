# Bug Log

Every entry here must result in a permanent case added to `backend/tests/golden/`
before it's marked resolved. A patched bug without a regression case is not
resolved — it's just hidden until the next rewrite.

---

## 2026-09-17 — Spill area omits cos(latitude), overstating every km2 figure
- **Symptom:** Reported `area_sq_km` for a slick at 19 deg N is ~6% larger than the true
  geodesic area; the error grows with latitude (~29% at 45 deg N, ~50% at 60 deg N).
  Every downstream figure inherits it: severity banding, Bonn Agreement volume, and the
  environmental-damage number quoted in the dossier.
- **Root cause:** `pixels_to_geo` computed
  `area_px * (lon_range*111/W) * (lat_range*111/H)`, treating one degree of longitude as
  111 km at every latitude. A degree of longitude is `111 * cos(lat)` km.
- **Stage/module:** Stage 1 boundary, `apps/detection/postprocessing.py`
- **Regression case added:** `backend/tests/golden/test_golden_geodesy.py` — cases 1-4
- **Status:** fixed

## 2026-09-17 — Sigmoid silently skipped when logits happen to land inside [0,1]
- **Symptom:** LATENT, not observed in production. Verified by construction: on the shipped
  `best_unet_dice_0.8018` checkpoint against the bundled calibration scene, 0 of 12 tiles
  trigger the faulty branch, so the deployed demo is currently unaffected. The defect is a
  reachable correctness hole rather than a live failure, and is reproduced in the regression
  test with a head whose logits are confined to [0, 1]. Where it does fire, the effect is
  scene-dependent over-detection: probabilities read too high, marginal regions cross the
  0.5 threshold.
- **Root cause:** `predict_single_tile` inferred whether the head was already activated by
  inspecting the output range: `if out.min() < 0 or out.max() > 1: sigmoid(out)`. For a tile
  whose logits all fall within [0, 1] — weakly positive everywhere, which is common on
  low-contrast water — the branch is skipped and raw logits are used as probabilities.
  Logit 0.9 is a probability of 0.71, but was read as 0.90, pushing the region over the
  0.5 threshold. The activation state of a model head is a property of the checkpoint, not
  of one tile's values, and must not be inferred per-call.
- **Stage/module:** Stage 1, `apps/detection/inference.py`
- **Regression case added:** `backend/tests/golden/test_golden_inference.py` — cases 1-3
- **Status:** fixed

## 2026-09-17 — Every detected polygon reported confidence 1.0
- **Symptom:** The dossier displayed "100% confidence" for every region, including marginal
  ones. Operators had no way to triage which detections to trust.
- **Root cause:** `ModelManager.predict()` thresholded the probability map internally and
  returned only a binary uint8 mask, so `mask_to_polygons` had no soft scores left to
  average and hardcoded `confidence = 1.0`.
- **Stage/module:** Stage 1 boundary, `apps/detection/inference.py` -> `postprocessing.py`
- **Regression case added:** `backend/tests/golden/test_golden_inference.py` — cases 4-6
- **Status:** fixed

## 2026-09-17 — Tile overlap fused with max(), biasing toward false positives
- **Symptom:** Grid-aligned seams visible in output masks at multiples of the 224 px stride;
  small spurious detections surviving at tile boundaries.
- **Root cause:** Overlapping tile predictions were combined with `np.maximum`. A single
  over-confident tile wins outright over its neighbours, so every disagreement resolves in
  favour of detection, and U-Net edge artefacts (which are worst at tile borders) are
  preserved rather than averaged away.
- **Stage/module:** Stage 1, `apps/detection/inference.py`
- **Regression case added:** `backend/tests/golden/test_golden_inference.py` — cases 7-8
- **Status:** fixed

## 2026-09-17 — Proximity and time scored independently, enabling wrong-time attribution
- **Symptom:** A vessel 1 km from the reconstructed origin but 40 hours before the release
  time received a composite score close to a vessel that was at the origin at the release
  time. On a busy shipping lane this is the difference between naming the polluter and
  naming whoever happened to transit the area that week.
- **Root cause:** `score_vessels` computed `proximity_score` from the minimum distance over
  all pings and `temporal_score` from the minimum time offset over all pings, then summed
  them with fixed weights. The two minima may come from different pings, so the score
  rewards "near at some point" and "present at some point" independently rather than
  "near at the right time". It also used the nearest discrete ping rather than the true
  closest point of approach, an error of several km for a vessel moving at 15 kn between
  10-minute pings.
- **Stage/module:** Stage 3, `apps/ais/scoring.py`
- **Regression case added:** `backend/tests/golden/test_golden_attribution.py` — cases 1-4
- **Status:** fixed (superseded by `apps/ais/attribution.py`; legacy scorer retained)

## 2026-09-17 — Origin uncertainty was a fabricated constant
- **Symptom:** `origin_uncertainty_km` was always `2.0 + 0.5 * duration_hours`, i.e. exactly
  14 km for every 24 h hindcast regardless of wind strength, current strength or their
  variability. The uncertainty circle drawn on the map carried no information.
- **Root cause:** No uncertainty model existed. The formula was a placeholder.
- **Stage/module:** Stage 2, `apps/drift/engines/lagrangian.py`
- **Regression case added:** `backend/tests/golden/test_golden_ensemble.py` — cases 1-6
- **Status:** fixed (Monte Carlo ensemble in `apps/drift/engines/ensemble.py`)

## 2026-09-17 — Test suite requires a live Redis; "13/13 passing" not reproducible
- **Symptom:** On a clean checkout with no Redis running, 5 of 10 collectable tests fail with
  `redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379`, and
  `test_model_hotswap.py` fails to import without torch. The documented "13/13 tests passing"
  cannot be reproduced by a judge cloning the repository.
- **Root cause:** `CACHES.default` pointed unconditionally at `RedisCache`, including under
  pytest. Django's `locmem` backend satisfies every cache call these tests make.
- **Stage/module:** Cross-cutting, `backend/config/settings.py`
- **Regression case added:** `backend/tests/golden/test_golden_environment.py` — case 1
- **Status:** fixed

## 2026-09-17 — Single met-ocean sample held constant across the whole hindcast
- **Symptom:** A 24 h or 48 h backward trajectory was advected using one wind vector and one
  current vector sampled at the detection point at detection time. Reconstructed origins in
  a sea breeze regime or a tidal current were displaced by tens of km.
- **Root cause:** `orchestrator.run_pipeline` called `fetch_metocean_vectors` once per region
  and passed scalars into `DriftInput`; `LagrangianDriftEngine` had no mechanism to re-sample
  the field along the trajectory.
- **Stage/module:** Stage 2, `apps/drift/metocean.py` and `orchestrator.py`
- **Regression case added:** `backend/tests/golden/test_golden_ensemble.py` — case 7
- **Status:** fixed (time-varying `metocean_provider` hook on the ensemble engine)

## 2026-09-17 — Wind-driven drift applied with no Coriolis/Ekman deflection
- **Symptom:** Wind-driven component pushed exactly downwind. Observed oil drifts to the
  right of the wind in the Northern Hemisphere (left in the Southern) by roughly 15-25 deg.
- **Root cause:** `LagrangianDriftEngine` implemented `V = V_current + 0.03 * V_wind` with no
  rotation term. The 3% windage factor is standard; the deflection angle that accompanies it
  in operational spill models was omitted.
- **Stage/module:** Stage 2, `apps/drift/engines/lagrangian.py`
- **Regression case added:** `backend/tests/golden/test_golden_ensemble.py` — case 8
- **Status:** fixed (hemisphere-aware deflection in the ensemble engine; the legacy
  deterministic engine is left untouched so its existing unit tests remain valid)

---

## Adversarial review pass, 2026-09-17
Found by an adversarial pass over the code written earlier the same day, run as a
separate pass whose only goal was to break the new modules rather than confirm them.
All four were in new code and none were caught by the contract-conformance checks,
which is the point of running the two passes separately.

## 2026-09-17 — Met-ocean perturbations compounded geometrically each step
- **Symptom:** With a time-varying met-ocean provider whose field differs from the
  initial parameters, the wind speed used by the ensemble doubled every step. A stub
  provider returning a constant 8 m/s was read as 8, 16, 32, 63, 126, 252 m/s over six
  hourly steps. Reconstructed origins were displaced by hundreds of km.
- **Root cause:** Each particle's error draw was stored as an already-perturbed speed,
  and the per-step re-application recovered the factor as
  `wind_speed / params.wind_speed_mps` -- using the mutated `wind_speed` as the
  numerator. The factor therefore multiplied itself each step. It was invisible in the
  first test because that stub returned the same field as the base parameters, making
  the ratio exactly 1.0; it only fires when the live field differs from the initial
  parameters, which is every real run.
- **Stage/module:** Stage 3, `apps/drift/engines/ensemble.py`
- **Regression case added:** `backend/tests/golden/test_golden_ensemble.py` — case 9
- **Status:** fixed (error draws stored as factors/offsets, applied to the fresh field)

## 2026-09-17 — Attribution verdict depended on traffic density, not evidence
- **Symptom:** An identical, perfectly-matching vessel scored 0.93 posterior
  ("strong") with no other traffic present and 0.06 ("insufficient") with 199
  irrelevant vessels elsewhere in the AIS window. The culprit's own evidence was
  byte-identical in both cases; only the vessel count changed. On real MarineCadastre
  data for a lane like the approaches to Mumbai, which routinely carries 100+ vessels
  in a 48 h window, the system would have refused to attribute anything at all.
- **Root cause:** `attribute()` split a fixed prior mass `(1 - prior_unknown)` evenly
  across however many vessels the query returned, so each vessel's prior shrank in
  proportion to unrelated traffic. Vessels the ensemble cannot place already
  contribute a likelihood of zero, so they should not have influenced the result.
- **Stage/module:** Stage 4, `apps/ais/attribution.py`
- **Regression case added:** `backend/tests/golden/test_golden_attribution.py` — case 5
- **Status:** fixed (constant per-vessel prior weight, normalised after the fact)

## 2026-09-17 — Drift ensemble varied release position but not release time
- **Symptom:** Every particle in the ensemble carried an identical release timestamp,
  so the attribution stage's stated "joint in space and time" likelihood was joint in
  space only. A vessel was tested against one candidate release time rather than the
  distribution of plausible ones, which understates the likelihood for any vessel
  whose transit timing was slightly off the nominal hindcast duration.
- **Root cause:** The integration ran a fixed number of steps for every particle, so
  all particles reached their origin at the same instant. The time the slick spent
  adrift is itself uncertain and was never sampled.
- **Stage/module:** Stage 3, `apps/drift/engines/ensemble.py`
- **Regression case added:** `backend/tests/golden/test_golden_ensemble.py` — case 10
- **Status:** fixed (per-particle release step drawn from `duration_sigma_frac`;
  particles freeze at their own release step)

## 2026-09-17 — Interior holes counted inside region statistics
- **Symptom:** A ring-shaped slick reported confidence 0.76 where the oil itself had a
  posterior of 0.90, because the open water in the middle was averaged in. The same
  mask is passed to the look-alike classifier, so the open-water interior also
  corrupted the interior-homogeneity and damping-contrast features that decide whether
  a region is oil at all.
- **Root cause:** `_contour_stats` filled the outer contour without punching out the
  child (hole) contours that `mask_to_polygons` had already identified.
- **Stage/module:** Stage 1/2 boundary, `apps/detection/postprocessing.py`
- **Regression case added:** `backend/tests/golden/test_golden_geodesy.py` — case 5
- **Status:** fixed

## 2026-09-17 — A Redis outage killed the whole pipeline, not just the cache
- **Symptom:** With no Redis running, `run_pipeline` aborted with
  `redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379`. Found
  while running the first real end-to-end integration against the calibration scene.
  Runs with a manual met-ocean override, which never need the network at all, died
  the same way.
- **Root cause:** `fetch_metocean_vectors` guarded its HTTP calls with try/except but
  called `cache.get()` and `cache.set()` outside that guard. Redis here is a cache of
  values that can always be re-fetched, so losing it should cost latency, never
  availability.
- **Stage/module:** Stage 2/3, `apps/drift/metocean.py`
- **Regression case added:** `backend/tests/golden/test_golden_environment.py` — cases 4-5
- **Status:** fixed (`_cache_get` / `_cache_set` treat an unreachable cache as a miss)

## 2026-09-17 — Time-varying met-ocean cost one HTTP round trip per hour
- **Symptom:** The drift stage took 33,761 ms on a 24 h hindcast, against a project
  claim of end-to-end analysis "in under 60 seconds". Measured on the real
  calibration scene with live Open-Meteo data.
- **Root cause:** `make_trajectory_provider` called `fetch_metocean_vectors` once per
  integration step, so a 24-step hindcast made 24 sequential API calls. Open-Meteo
  returns hourly series natively, so the whole window can be retrieved in one request.
- **Stage/module:** Stage 3, `apps/drift/metocean.py` and `orchestrator.py`
- **Regression case added:** `backend/tests/golden/test_golden_environment.py` — case 5
- **Status:** fixed (`make_timeseries_provider`, one batched fetch; drift stage
  33,761 ms -> 2,674 ms, a 12.6x speedup, total pipeline ~9.7 s)

## 2026-09-17 — Unknown-vessel hypothesis was not on the same scale as the vessels
- **Symptom:** On the real end-to-end case the correct vessel sat 0.90 km from the
  reconstructed origin at the reconstructed release time, with a 90-minute
  transponder blackout over the release window, and the system still concluded
  "insufficient evidence" with the unknown hypothesis at 100%.
- **Root cause:** A tracked vessel's likelihood is a capture fraction, which
  necessarily shrinks as the drift ensemble spreads, while `unknown_likelihood` was a
  fixed 0.25. The two are different scales, so on any long hindcast the unknown
  hypothesis won automatically -- not because the evidence favoured a dark vessel but
  because the ensemble was diffuse. The verdict tracked a modelling artefact rather
  than the evidence.
- **Stage/module:** Stage 4, `apps/ais/attribution.py`
- **Regression case added:** `backend/tests/golden/test_golden_attribution.py` — cases 4, 5b
- **Status:** fixed (the unknown vessel's likelihood is now the capture achievable by
  coincidence alone -- kernel area over ensemble search area -- so a tracked vessel
  must beat chance. The same real case now returns 72% posterior, verdict "strong",
  while the 30 km-away variant still correctly returns insufficient evidence.)

---

## 2026-09-17 — CRITICAL: the shipped "ground-truth SAR calibration image" is digital artwork
- **Symptom:** `ai_model/calibration_data/known_sar_spill.jpg`, documented in both
  `README.md` and `ai_model/README.md` as *"Ground-truth SAR image with confirmed oil
  slick for calibration"*, is a piece of digital artwork depicting a person's head. It
  contains no ocean, no oil and no ground truth. Found by rendering the case dossier's
  imagery panel during a real end-to-end run and looking at what was actually analysed.

  Three consequences, all of which were live:
  1. The Layer 1 SAR domain gate **accepted it as authentic SAR**
     (`Passed SAR verification (min_corr=0.954, flat_ratio=0.6%)`).
  2. The full pipeline ran on it to completion and produced a confident forensic
     dossier: 1470 km2 of "oil" at 95.8% model confidence, 99% oil probability from the
     look-alike screen, a reconstructed release point, and a named prime suspect vessel
     at 72% posterior. A picture of someone's ear produced a maritime pollution
     accusation.
  3. `validate_checkpoint.py` step 5 used this file for its side-by-side behavioural
     comparison, so **every checkpoint that ever "passed validation" was benchmarked
     against a drawing.**
- **Root cause:** Two independent gaps. The domain gate tested only channel
  decorrelation and zero-variance blocks; a near-greyscale artwork satisfies both. It
  never tested for speckle, which is the defining property of a coherent radar image:
  SAR carries multiplicative noise in every resolution cell, so the local coefficient
  of variation stays near 1/sqrt(L) everywhere, including inside dark regions.
  Measured: the artwork has median local CV 0.108 with 28% of the frame locally smooth;
  4-look SAR has CV 0.49 with 0% smooth. Separately, the validation gate never checked
  that its own calibration fixture was admissible input.
- **Stage/module:** Layer 1, `apps/detection/preprocessing.py`; and
  `ai_model/scripts/validate_checkpoint.py`
- **Regression case added:** `backend/tests/golden/test_golden_sar_gate.py` — cases 1-10
- **Status:** fixed. The gate now measures speckle and rejects the file (verified against
  positive controls at 1, 2, 4, 16 and 64 looks, plus despeckled and JPEG-compressed
  SAR, which all still pass). `validate_checkpoint.py` now verifies its calibration
  asset is admissible SAR before using it and fails loudly when none is. A replacement
  asset with real ground truth is generated by
  `ai_model/calibration_data/make_calibration_scene.py`. The artwork is deliberately
  left in place so the regression test can keep proving it is rejected.
- **Still open for a human:** the replacement is synthetic. A real Sentinel-1 scene with
  a hand-verified slick mask (Copernicus Open Access Hub, or the CleanSeaNet archive)
  should replace it before any performance number is published.

## 2026-09-17 — Look-alike discriminator measured brightness twice, not speckle damping
- **Symptom:** On a controlled scene containing one true slick and one calm-wind decoy
  of identical darkness, the discriminator scored **both** at 0.990 "probable oil". The
  decoy is the single most common SAR oil false positive, and the feature built to
  reject it had no discriminating power at all.
- **Root cause:** `interior_homogeneity` was computed as
  `1 - interior_std / scene_std`. SAR speckle is MULTIPLICATIVE, so the local standard
  deviation scales with the local mean; any dark region therefore has a low absolute
  std. The feature was measuring darkness a second time, in a model where
  `damping_contrast` already measured it and was saturated for both regions. Dividing
  by the mean removes the brightness dependence: measured on that scene, the CV ratio
  inside-to-outside was 0.56 for the true slick against 0.99 for the decoy.
  Two weighting errors compounded it: `damping_contrast` carried 3.40 log-odds, though
  darkness is necessary but not remotely sufficient for oil; and `wind_plausibility`
  was centred like an ordinary feature, so "the wind was workable" was worth +3.00
  log-odds of positive evidence on its own.
- **Stage/module:** Layer 2, `apps/detection/lookalike.py`
- **Regression case added:** `backend/tests/golden/test_golden_lookalike.py` — cases
  5b, 5c, 13
- **Status:** fixed. The feature is now the coefficient-of-variation ratio;
  `damping_contrast` is down-weighted to 1.80; wind is applied as a penalty only, and
  contributes exactly zero when unknown. The same scene now separates cleanly:
  0.985 for the true slick against 0.063 for the decoy.
- **Note for review:** golden cases 1 and 5 in `test_golden_lookalike.py` build their
  scenes with additive Gaussian noise, which SAR does not obey, so their CV ratio is
  exactly 1.0 by construction. Their assertions remain correct but are not achievable
  on a physically realisable SAR scene. Per the frozen-golden-tests rule they were left
  byte-identical and marked `xfail` with that explanation rather than rewritten, and
  replacements built on gamma speckle were added as cases 1b and 5b.
  **A human should decide whether to retire the two originals.**

## 2026-09-17 — SegFormer checkpoint silently fell back to the U-Net on hot-swap
- **Symptom:** Pointing `MODEL_CHECKPOINT_PATH` at `best_segformer_b0.pth` produced a
  running system that reported success and served the OLD U-Net. `ModelManager.reload`
  returned `is_fallback: True` with a `fallback_reason` of missing UNet keys, but
  nothing in the deployment path required anyone to read that flag, so the better
  model would simply never have been in use.
- **Root cause:** The checkpoint stores its tensors under a custom module layout
  (`segformer.stages.N.blocks.M.attention.q_proj`) matching neither
  `segmentation_models_pytorch` nor HuggingFace's `SegformerForSemanticSegmentation`
  (`segformer.encoder.block.N.M.attention.self.query`). `instantiate_model()` had no
  branch that could build it, so the state dict was loaded into a `UNet`, failed, and
  the fail-safe did exactly what it was designed to do. The fail-safe was correct; the
  missing architecture was the defect.
- **Stage/module:** Stage 1, `apps/detection/inference.py`
- **Regression case added:** `backend/tests/golden/test_golden_segformer.py` — cases 1-8
- **Status:** fixed. The architecture is reconstructed from the tensor shapes in
  `apps/detection/architectures/segformer.py` (MiT-B0: dims 32/64/160/256, depths
  2/2/2/2, SR ratios 8/4/2/1, MLP ratio 4) and loads with `strict=True` — all 208
  tensors claimed, none left randomly initialised. Registered under the aliases
  `segformer`, `segformer_b0` and `mit_b0`. The decoder concatenation order was
  determined empirically rather than assumed: reversed (c4..c1) scores Dice 0.59 on the
  ground-truth calibration scene, forward order scores 0.00.
- **Note:** the UI already surfaces `model.is_fallback` as a "fallback model" badge on
  the case page, so a silent downgrade would now be visible to an operator. That badge
  is the reason this class of failure is worth surfacing rather than only logging.

## 2026-09-18 — Test-time augmentation measured HARMFUL on SAR
- **Symptom:** Enabling the 4-way flip TTA built earlier degraded detection rather than
  improving it: on the calibration scene Dice fell 0.575 -> 0.506 and recall 0.962 ->
  0.801, for four times the compute.
- **Root cause:** Flip augmentation assumes the imaging geometry is orientation-
  invariant. SAR is not: a Sentinel-1 GRD carries a cross-swath incidence-angle
  brightness gradient, so a horizontally flipped tile presents a gradient running the
  wrong way, which is an input the model never saw in training. Averaging the correct
  view with three implausible ones pulls the posterior down, and the loss falls almost
  entirely on recall.
- **Stage/module:** Stage 1, `apps/detection/inference.py` / `config/settings.py`
- **Regression case added:** covered by the benchmark harness
  (`ai_model/scripts/benchmark_models.py --tta`); `MODEL_TTA` documented as harmful
- **Status:** fixed by remaining OFF by default, with the measurement recorded beside
  the setting so nobody enables it expecting a gain. The code is retained because the
  same machinery produces a per-pixel epistemic uncertainty map, which is useful for
  a different purpose.

## 2026-09-18 — Model selection was being made on a single scene
- **Symptom:** The SegFormer checkpoint reports better validation metrics than the
  U-Net (Dice 0.8245 vs 0.8018, IoU 0.7294 vs 0.6692) and is 9x faster, which looked
  like a clear-cut upgrade. On the one available ground-truth scene it was in fact
  slightly WORSE (effective Dice 0.957 vs 0.989). One scene is an anecdote, not
  evidence, and the two numbers pointed in opposite directions.
- **Root cause:** No benchmark existed. The only ground-truth asset was a single
  scene, and the reported metrics came from each checkpoint's own validation split,
  which are not known to be the same split.
- **Stage/module:** Model selection, `ai_model/`
- **Regression case added:** `ai_model/calibration_data/make_benchmark_suite.py` (11
  scenes: 8 with slicks across geometry/speckle/contrast, 3 clean-water false-positive
  controls) and `ai_model/scripts/benchmark_models.py`
- **Status:** fixed. Measured across the suite, neither model dominates — the U-Net
  scores 0.000 effective Dice on a scene where SegFormer reaches 0.141, and SegFormer
  scores 0.000 where the U-Net reaches 0.994. Averaging the two posteriors beats both
  (0.613 vs 0.590 and 0.401) and beats both members on the noisiest scene (0.958 vs
  0.578 and 0.931). The ensemble is now the default.
- **Known limitation, unresolved:** BOTH models score 0.000 on faint slicks (damping
  ~0.45-0.48, i.e. only about twice as dark as the surrounding sea). Neither detects
  low-contrast films at all. This is a training-data gap, not a threshold that can be
  tuned around, and it is the single largest accuracy gap remaining.

---

## Model security audit, 2026-09-18

## 2026-09-18 — CRITICAL: arbitrary code execution when loading a checkpoint
- **Symptom:** A 2 KB file advertising `val_dice: 0.99` executed a shell command the
  instant it was loaded, before any architecture or tensor-shape check could reject
  it. Demonstrated with a benign payload that wrote a marker file; a real one would
  read the AIS database or the chain-of-custody material.
- **Root cause:** A PyTorch checkpoint is a pickle, and unpickling is arbitrary code
  execution. Two paths were affected: `torch.load(..., weights_only=False)` for
  single-file checkpoints, and a bare `pickle.Unpickler` in
  `_load_checkpoint_directory` for directory-format ones. An object whose
  `__reduce__` returns `(os.system, ("...",))` runs during load.
- **Threat model:** Not remotely reachable -- `reload()` is not exposed by any API
  endpoint, so it needs a file on disk. But that is precisely the documented hot-swap
  workflow: "place new weights in `ai_model/weights/` and point
  `MODEL_CHECKPOINT_PATH` at it." Checkpoints are routinely downloaded from model
  zoos and shared between team members, which is the standard ML supply-chain attack.
- **Stage/module:** Stage 1, `apps/detection/inference.py`
- **Regression case added:** `backend/tests/golden/test_golden_model_security.py` —
  cases 1-4
- **Status:** fixed. Single-file loads use `weights_only=True` (data only, no global
  lookups, no execution). Directory loads go through a `_RestrictedUnpickler` whose
  allowlist contains only the torch/collections/numpy globals a state dict legitimately
  needs; anything else raises `UnsafeCheckpointError` naming the offending symbol.
  `ALLOW_UNSAFE_CHECKPOINTS` exists for a legacy checkpoint that cannot be re-exported
  and is off by default. Both shipped checkpoints still load.

## 2026-09-18 — Adversarial perturbation flips the detector in both directions
- **Symptom:** Bounded PGD against the segmentation head:
    - **Evasion** at eps = 1/255 (a single grey level, invisible) reduced a real slick
      from 16,687 detected pixels to **0**. A polluter could defeat detection entirely.
    - **Injection** at eps = 4/255 manufactured **5,117 px** of "oil" on clean water,
      rising to 18,459 px at 8/255. An innocent vessel could be framed.
- **Threat model:** The satellite feed cannot be perturbed by an attacker, so this is
  not a risk for Sentinel-1 ingestion. It IS a risk on the upload path, which the
  console exposes: a doctored scene submitted as evidence.
- **Mitigation that holds — injection:** the Layer 2 physics screen rejects it.
  Gradient descent moves the pixels the network reads, but does not reproduce the
  speckle damping mineral oil causes. The 18,459 px injected region was rejected at
  `p_oil = 0.010`, with the decisive evidence being `interior_homogeneity` at
  -3.00 log-odds. The attack cannot reach that statistic because it is measured from
  the image directly, not from the network.
- **NOT mitigated — evasion:** Layer 2 only ever removes candidates. If the head is
  driven to detect nothing, there is nothing to screen. This asymmetry is inherent.
- **Status:** injection mitigated and pinned by test; evasion documented as an open
  limitation. For a forensic tool the asymmetry is the right way round -- a missed
  detection loses a case, a false accusation harms someone -- but it is a real
  limitation and is stated rather than papered over.
- **Regression case added:** `backend/tests/golden/test_golden_model_security.py` —
  cases 5-8

## 2026-09-18 — Mean-combining lets one attacked ensemble member veto the others
- **Symptom:** A PGD attack crafted against SegFormer alone did NOT transfer -- the
  U-Net still detected 11,700 px, essentially unaffected. Yet the ensemble output
  fell to **0 px**. A single compromised member silently vetoed a correct one.
- **Root cause:** Mean-combining. A confident 0 from the attacked member averaged with
  a confident 1 from the honest member lands at exactly 0.5, which does not exceed the
  0.5 decision threshold. The ensemble was adopted partly for robustness and in this
  respect was weaker than its own best member.
- **Stage/module:** Stage 1, `apps/detection/inference.py`
- **Status:** documented, default unchanged, alternatives measured and rejected:
    - `MODEL_COMBINER=max` is evasion-resistant (an attacker must defeat every
      member) but effective Dice falls 0.613 -> 0.369 on clean imagery.
    - Median-filter purification defeats the attack in isolation (restoring Dice from
      0.000 to 0.552) but **destroys the speckle statistic both physics layers depend
      on**: local CV 0.251 -> 0.100 at 3x3 and 0.056 at 5x5, where the scene no longer
      passes the Layer 1 SAR gate at all. Effective Dice falls 0.613 -> 0.350. The
      adversarial defence and the physics defences are incompatible.
    - Member disagreement was evaluated as an attack detector and **rejected**: 17.85%
      of the scene under attack against 16.34% on a legitimately noisy scene, a
      separation of 1.1x. Not usable.
  `mean` with no purification remains the default because the satellite feed is
  trusted and it is the most accurate configuration there. `MODEL_COMBINER=max` is
  available as a hardened mode for untrusted uploads.
- **Regression case added:** `test_golden_model_security.py` — cases 7-8
