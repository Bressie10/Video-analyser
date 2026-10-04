# ContentMetric V8.5 — Intelligence Foundations release candidate

## Purpose and boundary

V8.5 freezes the versioned intelligence schemas and ontology, supplies a human annotation method, and provides offline agreement, low-level V8 evaluation, and benchmark-normalization experiments. It creates evidence and decision rules for V9. It does not add a detector, product score, route, migration, frontend flow, external acquisition, model call, or production recommendation behavior. The frozen `backend/intelligence/schemas/`, `backend/intelligence/ontology/`, and `backend/intelligence/versions.py` are byte-for-byte unchanged from `3a07b548dcc9d7c3ef1e2d31b8e0526d626ac16d` in this candidate.

## What we learned about V8

The existing pipeline reports FFprobe stream metadata and uses heuristics for ASR transcript segments, PySceneDetect scene boundaries, sampled-frame OCR text tracks, and optical-flow motion events. Raw observation means decoded media or stream properties. A heuristic signal is a detector's fallible report. A derived detector-output statistic, such as `scene_boundaries_first_5_seconds`, counts those reports and inherits their errors. Semantic interpretation asks what the content means or how it was edited. The checked-in baseline evaluates selected low-level outputs, not the semantic ontology.

A scene boundary is not an editorial or jump cut; OCR text is not automatically a caption; a `camera_zoom` flow event is not a verified zoom or punch-in. A transcript question does not establish a question hook, and speech does not establish a visible talking-head format. A scene change alone does not establish a pattern interrupt. V8 has no direct detector for hook intent, CTA, format, structure roles, music/sound effects, visual subjects, text role, or edit type. The existing generated-media check is an easy synthetic sanity case, not a real-world precision or recall estimate. See [the signal matrix and baseline limits](V8_5_EXISTING_ANALYSIS_BASELINE.md).

## Annotation system

The frozen ontology names techniques and structure roles; guideline **1.1.0** supplies operational human decisions. Its opening-window, talking-head, and pattern-interrupt thresholds are V8.5 reproducibility conventions, not universal content truths. The guidelines permit independently supported overlapping labels and explain difficult pairs. Annotators must record the guideline version and evidence for borderline decisions. An unreviewed, unresolved, or incomplete category is never a negative. A complete category with no label is a reviewed negative. Numeric fields require a separate agreed field catalogue, units, method, and evidence; the frozen contract does not define a universal numeric feature catalogue.

Begin with 10–15 varied real videos labelled independently by at least two annotators, covering ordinary and weak material as well as polished material. Inspect per-label presence, interval union IoU, point timing distances and unmatched points, structure-role overlap, prevalence, and coverage. Adjudicate against media while preserving independent records. Revise and version the guideline if decisions change. Then assemble a rights-cleared 60–100-video set, grouped by creator and near-duplicate concept before train/validation/test splitting; double-label at least 20–30%, with extra overlap for rare and disputed labels. The CLI validates the frozen contracts and source/split declarations, summarizes coverage, and rejects agreement comparisons across guideline versions. It cannot detect perceptual duplicates or prove adjudication quality. Visual-hook intent, talking-head share, format coexistence, pattern interrupts, and role boundaries remain subjective pilot targets. See [guidelines and pilot workflow](backend/intelligence/evaluation/README.md).

## Benchmark intelligence

V8 stores nullable retrieved count snapshots. Provider fields and observation windows differ: Instagram views, Facebook video views, Facebook Reel plays, Meta ad three-second views, TikTok counts, reach, impressions, and actions are not interchangeable. Paid and organic exposure cannot silently share a cohort. A null means unknown, not zero. Absolute views measure reach under distribution conditions, not content quality; high absolute views do not by themselves mean account-relative outperformance. Selecting only top videos creates outcome-selection bias. Neither association with a technique nor relative outperformance proves causation.

The offline harness consumes frozen `BenchmarkVideo` documents. Peer-video experiments require matching declared platform, account, exposure, snapshot source, content type, metric definition, attribution context, and declared format; an explicit publication-to-fetch observation window and publication age are required. Known conflicts, unknown or mixed exposure, null metrics, and cohorts under five distinct sources are ineligible. Exact provider IDs or URLs deduplicate eligible snapshots and exclude target aliases. Unknown format or attribution context remains an explicit limitation, so eligibility is conditional on unverified declarations. The two-day age tolerance and five-source minimum are easy-to-find research constants in `backend/intelligence/normalization.py`; neither is a validated production threshold. At present all peer methods use an age-matched same-account cohort, so the age-matched percentile is a diagnostic duplicate of the ordinary percentile, not independent evidence.

`AccountBaseline` is a separate precomputed account-cohort summary. Its frozen schema validates source, metric definitions, sample size, cohort window, and method reference, but does not independently prove membership, deduplication, exposure or publication-age compatibility. The research path therefore requires a separate structured `baseline_context`, target exclusion, a declared median method and matching metric definitions; unknown or conflicting context makes the result ineligible. It cannot compute percentile or dispersion from a median alone. Candidate outputs remain separate: median difference, ratio, log ratio, midrank percentile and robust deviation. There is no universal, viral, quality, or production score. Provider definitions, promotion history, cohort selection and matched-age sensitivity need a licensed data study before policy. See [normalization research](V8_5_BENCHMARK_NORMALIZATION_RESEARCH.md).

## V8 → V9 gap and interface fit

| Current evidence | Future requirement | Boundary to preserve |
| --- | --- | --- |
| ASR segments and OCR tracks | Audio-event/word evidence, caption alignment, hook and CTA interpretation | A word or question is evidence, not intent; OCR is text presence, not text role. |
| Scene boundaries and optical flow | Calibrated edit/shot continuity, zoom and composition recognition | Count `scene_boundaries_first_5_seconds` as a detector-output statistic; human editorial-cut truth needs a documented mapping and separate metric. |
| Metadata and speech presence | Visible speaker, subject, action, and format evidence | A speech track cannot establish talking-head or interview format. |
| Low-level timestamps | Narrative role and structure reasoning | No current output establishes a hook, payoff, pattern interrupt, or CTA. |
| Nullable provider snapshots | Comparable account-relative outcomes and cross-video patterns | Keep exact field/window/exposure provenance; do not infer missing context. |

The annotation dataset and V8 baseline evaluator can share source IDs and media references later without changing the frozen annotation contract. They currently use separate manifests and truth definitions: ontology labels and human numeric ground truth versus low-level scene/OCR/ASR/flow truth. A V9 evaluation adapter must explicitly map source IDs, producer versions, time bases, windows, coverage, guideline versions and numeric feature definitions; it must never convert an unchecked annotation into a negative. The example human `cuts_first_5_seconds` value represents an invented editorial cut, while the V8-safe derived name is `scene_boundaries_first_5_seconds`; equating them would overstate V8. Benchmark research can parse the frozen `BenchmarkVideo` directly, but the contract alone does not supply every cohort qualification field. External, auditable context is needed for account baselines, and real provider records need verified metric definitions and acquisition provenance. These are V9 interface/data curation gaps, not reasons to change the frozen contracts.

## Final V9 priority order

1. **Calibrate V8 low-level signals** on a representative, rights-cleared labelled set. Measure ASR, OCR, scene-boundary and flow precision, recall, timing, nulls and failure modes before promoting derived features.
2. **Expand audio evidence** for music, sound effects, silence, speech boundaries and word timing where needed. Validate each on the same set.
3. **Expand visual semantic evidence** for people, direct-to-camera speaking, subjects, actions, screen content, composition and shot continuity.
4. **Add narrow editing and text classifiers** for true cut type, punch-in/continuous zoom, caption-to-speech alignment and text role; allow abstention.
5. **Add hook, CTA and format understanding** using calibrated multimodal evidence and independent human labels.
6. **Add structure reasoning** over temporal context and recurring roles, after role agreement is measured.
7. **Build cross-video performance-pattern intelligence** only with provider-defined, exposure-compatible, age-aware, deduplicated histories; test account-relative methods separately from peer or baseline claims.
8. **Feed validated findings into recommendation generation** only after per-label utility and reliability are shown on held-out creators; avoid causal claims from correlation.

## V9 entry criteria

Before the first V9 detector stage, complete the 10–15-video double-labelled pilot with guideline 1.1.0 (or a newly versioned revision), record independent agreement and adjudication, and freeze a field catalogue for any numeric truth. Secure a representative real-world evaluation set that includes weak/ordinary/strong clips, varied formats, pacing, caption/music conditions, languages where supportable, and creator-disjoint splits with near-duplicates grouped. Record source rights, media duration, acquisition and producer versions; keep private media outside Git. Define per-signal low-level truth separately from semantic annotation, with explicit unreviewed states and tolerance policy. The first implementation stage should evaluate existing V8 outputs on the held-out set and publish per-signal errors and coverage before choosing a new detector. For performance research, verify provider metric definitions, observation windows, organic/paid status and source identities before eligible comparisons.

## Open questions and remaining risks

- What levels of per-label agreement, coverage, timing error and abstention make a semantic label useful for recommendations? The pilot must set thresholds from evidence, not assume them.
- Which numeric fields should be human-measured, which are detector-output statistics, and how will the independent annotation and V8 baseline manifests be joined and versioned?
- How should exact current provider view/play qualifications, revisions, promotion contamination, lifetime versus fixed-window counts, and account-history changes be verified?
- Is account-only normalization sufficient, or can a peer-creator cohort ever be qualified? What outcome demonstrates recommendation utility without treating distribution as quality or correlation as causation?
- Synthetic fixtures and generated media do not establish real creator-video accuracy. No live provider, production, or external media run is evidenced here.

## Candidate validation

The integrated worktree passed the complete backend `unittest discover` run against a disposable local PostgreSQL database with `RUN_MEDIA_INTEGRATION=1` and `HF_HUB_OFFLINE=1`: **431 tests, zero failures, zero skips**. The 36 focused contract, annotation, normalization and baseline tests passed independently. Annotation validate/agreement commands, the baseline synthetic fixture command, Python `compileall`, frozen-contract diff, production-path diff/import inspection and `git diff --check` also passed. The generated-media tests exercise local synthetic media, not licensed real creator videos or live provider APIs.

## Final audit answers

1. **Frozen contract unchanged?** Yes: no integrated diff under schemas, ontology or `versions.py` against the exact foundation.
2. **Experimental module affects production runtime?** No integration diff touches production routes, workers, recommendation generation, billing, auth, Meta code, migrations or frontend; production code has no import of these experimental modules.
3. **V8 signals represented as semantic understanding?** No in this candidate's documented conclusions. Legacy output names such as `cut_timestamp_seconds` and `camera_zoom` remain heuristic names and are qualified above.
4. **Benchmark research silently compares incompatible contexts?** The offline gates reject known mismatches and disclose unknown format/attribution limitations. Equality of free-form declarations is not independent provider verification; real-data curation remains required.
5. **Evaluation treats unreviewed absence as negative?** No. Agreement compares only jointly complete categories/structure; the baseline scores only supplied low-level truth sections, with explicit empty sections meaning checked negatives.
6. **Guideline thresholds provisional?** Yes, identified as V8.5 reproducibility conventions and subject to pilot revision.
7. **Universal/viral score?** No. Method-specific research outputs and per-signal evaluation metrics remain separate.
8. **Top five V9 priorities?** Calibrate existing signals; expand audio evidence; expand visual evidence; validate narrow edit/text classifiers; then validate hook/CTA/format understanding.
