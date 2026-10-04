# ContentMetric V8.5: Intelligence Foundations

## Purpose and boundary

V8.5 defines experimental data contracts for describing observable content techniques, human labels, and reference-video context. It does not detect techniques, acquire external videos, call models, train models, score virality, change recommendations, or expose an API. There are no database or frontend changes. Nothing under `backend/intelligence/` is imported by production routes, workers, or the V8 analysis pipeline.

The existing V8 `app.analysis_pipeline.analyze_file` remains the operational content-only pipeline. It returns media metadata, timestamped transcript segments, scenes, OCR text, and optical-flow motion events. The repository stores those observations separately from provider performance snapshots. Recommendation code interprets stored content and comparable performance evidence, while company profiles assemble bounded, company-authorized content and performance references with hashes, versions, retrieval times, and limitations. V8.5 does not alter any of those paths. A future adapter may translate stored V8 evidence into a new report, but V8 output is not automatically a V8.5 technique label: a scene boundary alone does not prove a jump cut, and OCR text alone does not prove captions.

## Ontology

`backend/intelligence/ontology/techniques.json` is the versioned vocabulary. Each entry has a stable hierarchical ID, name, description, category, temporal flag, observation kind (`point`, `interval`, or `whole_video`), overlap policy, and introduction version. `ontology.techniques()` validates every entry, rejects duplicates, and returns IDs for report and annotation validation. IDs in V1 cover hook, format, editing, text, structure, audio, CTA, and visual areas. `structure.pattern_interrupt` is a categorical event; `hook`, `value`, and `cta` phases are **structure segments** in their own timeline, not technique IDs. A whole-video format can coexist with another format, and a CTA modality can coexist with a CTA action.

Counts, rates, and durations belong in `derived_features`, with an ID, numeric value, unit, optional time window, and evidence references. Examples are `cuts_first_5_seconds`, `average_shot_length_seconds`, and `words_per_second`. They are not ontology labels. V1 omits ambiguous near-duplicates such as a generic `editing.cutaway` versus B-roll, and a generic `editing.zoom` versus punch-in. Those should be added only after annotation guidelines can distinguish them consistently.

The `overlaps_allowed` field records annotation policy, currently true for every V1 technique because modalities and events can coincide. Cross-observation overlap enforcement is deliberately deferred until labelling rules define precedence and equivalence. Stable IDs should keep their meaning; a changed meaning needs a new ID or a new ontology major version. Future ontology versions need a version-aware loader, not silent acceptance by this V1 validator.

## Analysis report

`schemas.report.AnalysisReport` is a strict Pydantic document. It requires source identity and optional known duration; report and ontology versions; a declaration of detector names and versions; technique observations with bounded confidence, valid timing, matching ontology ID and point/interval shape, detector identity, and evidence; temporal structure segments; derived numeric features; limitations; and run provenance including processing time and pipeline version. If duration is known, observations cannot extend beyond it. A report is facts only: it cannot assert that an observed technique caused performance. A report may be empty if no observation is supportable, with limitations explaining coverage. Detector versions are independent of report schema and ontology versions. Evidence references are opaque pointers for future adapters; the contract does not claim they are stored or resolved today.

Example shape (abridged):

```json
{
  "schema_version": "1.0.0",
  "ontology_version": "1.0.0",
  "techniques": [{"technique_id": "hook.question", "start_seconds": 0.2,
                  "end_seconds": 1.8, "confidence": 0.9,
                  "detector": {"name": "example-detector", "version": "0.1.0"},
                  "evidence": [{"kind": "transcript", "reference": "segment:0", "detail": null}]}],
  "structure": [{"role": "hook", "start_seconds": 0.0, "end_seconds": 2.1,
                 "confidence": 0.8, "detector": {"name": "example-detector", "version": "0.1.0"},
                 "evidence": [{"kind": "transcript", "reference": "segment:0", "detail": null}]}],
  "derived_features": [{"feature_id": "cuts_first_5_seconds", "value": 4.0,
                        "unit": "count", "window": {"start_seconds": 0.0,
                        "end_seconds": 5.0}, "evidence_refs": []}]
}
```

The complete document also requires `source`, `detector_versions`, `limitations`, and `provenance`.

## Human evaluation contract

`schemas.annotation.Annotation` records a source, ontology and annotation versions, unique annotation reference, annotator reference, technique spans, structure spans, known numeric ground truth, and notes. `AnnotationDataset` permits separate annotations for the same source and rejects duplicate annotation references. An annotator reference may be a pseudonym. This is a serializable file contract for a future manually labelled set of roughly 60–100 videos, not an annotation application or a set of acquired videos. Ground truth numeric features keep values and units separate from technique labels. Annotation disagreements are preserved as separate records; adjudication and split strategy remain open.

## Benchmark video contract

`schemas.benchmark.BenchmarkVideo` separates source provenance, creator context, publication context, a performance snapshot, an optional analysis report reference, and optional account baseline inputs. The source carries a platform, public/provider identifier or URL, acquisition method, and fetch time. A performance snapshot carries source, exposure type, observed metrics, metric definitions, window, and attribution context. Missing metrics may be omitted or explicitly `null`; neither becomes zero. An absent performance snapshot or baseline is `null`. There is no viral threshold or fixed normalization formula. Metrics remain tied to a retrieval time and their measurement context; paid, organic, shared ad, and unknown exposure need later research before comparisons. The contract is an internal representation, not an acquisition mechanism or claim that provider data is available.

## Versioning and future V9 use

`backend/intelligence/versions.py` is the single source for the four independent contract versions: ontology, analysis report, annotation, and benchmark. Each serialized document carries its applicable versions. Observation-level detector identity and version, plus run-level pipeline version, distinguish detector changes from contract changes. V1 validation rejects unsupported versions and unknown IDs; a future version must add explicit migration or compatibility handling. V9 can consume validated reports and evaluation labels, compare detector output with human labels, and explore normalization using benchmark context. It must keep observational extraction separate from performance interpretation and recommendations.

## Open product questions

- What exact annotation instructions distinguish hook types, B-roll, pattern interrupts, and overlapping formats? What constitutes a borderline or unlabelable case?
- Which source reference scheme can safely identify a video across providers, reposts, deletions, and edits?
- Which evidence pointers are durable enough to audit future detector decisions without retaining unnecessary media or personal data?
- Which metric definitions, exposure windows, account baselines, and publication ages are comparable across platforms and paid/organic contexts?
- How will multiple annotators resolve disagreements, and how will data splits avoid creator or near-duplicate leakage?
- How should a future engine express unavailable detector coverage versus an observed absence of a technique?

## Known risks and next stages

The initial vocabulary has not been calibrated against real labelled videos; ambiguous labels may require new IDs or guidance. Strong schema validation cannot establish that a detector's claim is true. Opaque evidence references and free-form feature IDs allow experimentation but need a registry and resolvers before production use. Performance snapshots can be incomplete or incomparable even when syntactically valid. Future stages are: author annotation guidelines and a representative licensed dataset; measure agreement; implement offline detector prototypes; evaluate precision, recall, calibration, and coverage by label; research benchmark normalization with preserved provenance; and only then design a production adapter and migration path if warranted.
