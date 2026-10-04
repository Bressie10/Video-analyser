# ContentMetric V8.5: Intelligence Foundations

## Purpose and boundary

V8.5 defines experimental data contracts for describing observable content techniques, human labels, and reference-video context. It does not detect techniques, acquire external videos, call models, train models, score virality, change recommendations, or expose an API. There are no database or frontend changes. Nothing under `backend/intelligence/` is imported by production routes, workers, or the V8 analysis pipeline.

The existing V8 `app.analysis_pipeline.analyze_file` remains the operational content-only pipeline. It returns media metadata, timestamped transcript segments, scenes, OCR text, and optical-flow motion events. The repository stores those observations separately from provider performance snapshots. Recommendation code interprets stored content and comparable performance evidence, while company profiles assemble bounded, company-authorized content and performance references with hashes, versions, retrieval times, and limitations. V8.5 does not alter any of those paths. A future adapter may translate stored V8 evidence into a new report, but V8 output is not automatically a V8.5 technique label: a scene boundary alone does not prove a jump cut, and OCR text alone does not prove captions.

## Ontology

`backend/intelligence/ontology/techniques.json` is the versioned vocabulary. Each entry has a stable hierarchical ID, name, description, category, temporal flag, observation kind (`point`, `interval`, or `whole_video`), overlap policy, and introduction version. `ontology.techniques()` validates every entry, rejects duplicates, and returns IDs for report and annotation validation. IDs in V1 cover hook, format, editing, text, structure, audio, CTA, and visual areas. `structure.pattern_interrupt` is a categorical event; `hook`, `value`, and `cta` phases are **structure segments** in their own timeline, not technique IDs. A whole-video format can coexist with another format, and a CTA modality can coexist with a CTA action.

Counts, rates, and durations belong in `derived_features`, with an ID, numeric value, unit, optional time window, evidence references, and a versioned producer. Examples are `cuts_first_5_seconds`, `average_shot_length_seconds`, and `words_per_second`. They are not ontology labels. V1 includes `editing.zoom` for a **continuous** visible scale change and `editing.punch_in` for an **abrupt** closer crop. `editing.transition` covers deliberate non-hard-cut transitions; a hard cut alone is not that label. `editing.picture_in_picture` is the specific inset-overlay pattern, visually distinguishable from a partitioned split screen. The existing broad `editing.split_screen` ID retains its meaning, so labels may overlap until annotation guidance defines precedence. These editing events are common enough for the small vocabulary. `editing.cutaway` remains omitted because its boundary with B-roll is not yet reliable.

The `overlaps_allowed` field records annotation policy, currently true for every V1 technique because modalities and events can coincide. Cross-observation overlap enforcement is deferred until labelling rules define precedence and equivalence. Stable IDs should keep their meaning; a changed meaning needs a new ID or a new ontology major version. The ontology snapshot is now 1.1.0. The loader requires an exact snapshot version and validates each `introduced_in` as a semantic version no later than that snapshot. Thus 1.0.0 entries remain valid in 1.1.0, while a 1.2.0 entry cannot appear in a 1.1.0 snapshot. This is version validation, not automatic migration.

## Structure roles

Structure segments are temporal phases, separate from categorical technique observations. The controlled V1 roles have these annotation meanings:

| Role | Meaning |
| --- | --- |
| `hook` | Opening device intended to secure initial attention. |
| `setup` | Context needed to understand what follows. |
| `problem` | Need, obstacle, or tension being addressed. |
| `explanation` | Explanatory or instructional value delivery. |
| `demonstration` | Showing a process, action, or product in use. |
| `proof` | Evidence, example, testimonial, or result supporting a claim. |
| `payoff` | Reveal, outcome, or resolution of an earlier setup. |
| `cta` | Request for a viewer action. |
| `other` | Material that does not fit a controlled role; annotator notes should explain. |

Roles describe function, not quality or performance. Adjacent segments may have different roles; an annotator may use multiple segments where functions change.

## Analysis report

`schemas.report.AnalysisReport` is a strict Pydantic document. It requires source identity and optional known duration; report and ontology versions; a declaration of producer names and versions; technique observations with bounded confidence, valid timing, matching ontology ID and point/interval shape, detector identity, and evidence; temporal structure segments; computed numeric features with their own producer/version; limitations; and run provenance including processing time and pipeline version. If duration is known, observations cannot extend beyond it. A report is facts only: it cannot assert that an observed technique caused performance. A report may be empty if no observation is supportable, with limitations explaining coverage. Producer versions are independent of report schema and ontology versions. Evidence references are opaque pointers for future adapters; the contract does not claim they are stored or resolved today.

Example shape (abridged):

```json
{
  "schema_version": "2.0.0",
  "ontology_version": "1.1.0",
  "techniques": [{"technique_id": "hook.question", "start_seconds": 0.2,
                  "end_seconds": 1.8, "confidence": 0.9,
                  "detector": {"name": "example-detector", "version": "0.1.0"},
                  "evidence": [{"kind": "transcript", "reference": "segment:0", "detail": null}]}],
  "structure": [{"role": "hook", "start_seconds": 0.0, "end_seconds": 2.1,
                 "confidence": 0.8, "detector": {"name": "example-detector", "version": "0.1.0"},
                 "evidence": [{"kind": "transcript", "reference": "segment:0", "detail": null}]}],
  "derived_features": [{"feature_id": "cuts_first_5_seconds", "value": 4.0,
                        "unit": "count", "window": {"start_seconds": 0.0,
                        "end_seconds": 5.0}, "evidence_refs": [],
                        "producer": {"name": "example-feature-code", "version": "0.1.0"}}]
}
```

The complete document also requires `source`, `producer_versions` (covering both detectors and feature producers), `limitations`, and `provenance`.

## Human evaluation contract

`schemas.annotation.Annotation` records a source, ontology and annotation versions, unique annotation reference, annotator reference, guideline version, timezone-aware `annotated_at`, technique spans, structure spans, known numeric ground truth, notes, and explicit coverage. An annotator reference may be a pseudonym. This is a serializable file contract for a future manually labelled set of roughly 60–100 videos, not an annotation application or a set of acquired videos. Human numeric ground truth has no automatic producer field.

`coverage.complete_technique_categories` lists categories exhaustively checked. A missing technique in one of those categories is a negative label; a missing technique in an unchecked category is **unknown**. Positive observations may still appear in an incompletely checked category. `coverage.structure_complete` says whether the full structure timeline was annotated; an empty structure list is negative only when this flag is true. `coverage.numeric_fields` gives each checked numeric field a status: `measured` requires exactly one ground-truth value, while `unavailable` or `not_applicable` requires an explanatory note and no value. An unlisted numeric field was not assessed.

`AnnotationDataset` permits separate, disagreeing annotations of one source while rejecting duplicate annotation references and inconsistent source identities for the same reference ID. Disagreements are preserved. Optional `split_assignments` contain exactly one partition per **source**, not per annotation; if supplied, every source is assigned once. Optional `group_ref` keeps known related sources in one partition. Near-duplicates and content from the same creator may require grouping before evaluation; the contract cannot discover those relationships itself. Adjudication remains open.

## Benchmark video contract

`schemas.benchmark.BenchmarkVideo` separates source provenance, creator context, publication context, a performance snapshot, an optional analysis report reference, and optional account baseline inputs. The source carries a platform, public/provider identifier or URL, acquisition method, and fetch time. Every recorded performance metric key, including a null value, requires a semantic definition with description, unit, and measurement basis. The snapshot also records source, exposure type, retrieval time, optional observation window, and attribution context. Numeric value alone is insufficient evidence. Missing metrics may be omitted or explicitly `null`; neither becomes zero. An absent performance snapshot or baseline is `null`.

If an account baseline is present, it requires a source, defined metric keys, positive sample size, timezone-aware time window, cohort definition, and method reference. This records what population produced the baseline without choosing a normalization formula. There is no viral threshold or assumed cross-platform comparability. Paid, organic, shared-ad, and unknown exposure need later research before comparisons. The contract is an internal representation, not an acquisition mechanism or claim that provider data is available.

## Versioning and future V9 use

`backend/intelligence/versions.py` is the single source for the four independent contract versions: ontology 1.1.0, analysis report 2.0.0, annotation 2.0.0, and benchmark 2.0.0. The three schema versions changed because their serialized contracts gained required fields or stronger required semantics. Each document carries its applicable versions. Observation-level detector and feature-producer versions, plus run-level pipeline version, distinguish algorithm changes from contract changes. Validation rejects unsupported document versions and unknown technique IDs; older documents need explicit migration or compatibility handling. V9 can consume validated reports and evaluation labels, compare detector output with human labels, and explore normalization using benchmark context. It must keep observational extraction separate from performance interpretation and recommendations.

## Open product questions

- What exact annotation instructions distinguish hook types, B-roll, pattern interrupts, and overlapping formats? What constitutes a borderline or unlabelable case?
- Which source reference scheme can safely identify a video across providers, reposts, deletions, and edits?
- Which evidence pointers are durable enough to audit future detector decisions without retaining unnecessary media or personal data?
- Which metric definitions, exposure windows, account baselines, and publication ages are comparable across platforms and paid/organic contexts?
- How will multiple annotators resolve disagreements, and which creator and near-duplicate grouping rules will prevent evaluation leakage?
- Which derived numeric features should become a controlled registry, with formally specified units and calculation windows?

## Known risks and next stages

The initial vocabulary has not been calibrated against real labelled videos; ambiguous labels may require new IDs or guidance. Strong schema validation cannot establish that a detector's claim or a provider's metric is true. Opaque evidence references and free-form feature IDs allow experimentation but need a registry and resolvers before production use. An annotation category marked complete is only as reliable as the annotator's review. Performance snapshots can be incomplete or incomparable even when syntactically valid. Future stages are: author annotation guidelines and a representative licensed dataset; measure agreement; implement offline detector prototypes; evaluate precision, recall, calibration, and coverage by label; research benchmark normalization with preserved provenance; and only then design a production adapter and migration path if warranted.
