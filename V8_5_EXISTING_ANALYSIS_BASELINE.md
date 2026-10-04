# V8.5 baseline of existing V8 analysis signals

## Scope and evidence

This audits `app.analysis_pipeline.analyze_file` and `app.video_processing` at base `3a07b548dcc9d7c3ef1e2d31b8e0526d626ac16d`. The frozen V8.5 ontology and schemas are read-only context. The offline evaluator and local fixtures live under `backend/intelligence/evaluation/`, beside the V8.5 ontology and schemas because they are research tooling for that namespace. It consumes V8 analysis JSON and separately authored low-level truth JSON; it neither changes the V8 pipeline nor produces ontology labels. The checked-in JSON fixture is **illustrative synthetic data**, not measured detector performance. The existing generated-video media test exercises a 4-second, 12 FPS 640×360 clip with a color change at 2 seconds, rendered `VIDEO TEST` text, a moving rectangle, and optional sine-wave audio. It does not represent real creator videos or spoken language.

The evidence ladder matters throughout this report: **raw observation** is decoded media or reported stream metadata; a **heuristic signal** is an ASR/OCR/scene/flow detector output that can be wrong; a **derived statistic** is arithmetic over specified outputs and retains their errors; a **semantic interpretation** is a claim such as a question hook, caption, jump cut, talking-head format or CTA. The current baseline evaluates selected low-level signals. It does not test those semantic interpretations. In particular, a scene boundary is not a jump cut, OCR text is not necessarily captions, a flow motion event is not a zoom or punch-in, transcript question wording is not necessarily a question hook, and detected speech does not establish a visible talking-head format.

## Capability matrix

| Signal | Current implementation and output shape | Claim supportable today | Claim not supportable / known failure modes | Possible V9 use |
| --- | --- | --- | --- | --- |
| Metadata | FFprobe on source before normalization; `metadata` contains duration, container, size, bit rates, video codec/resolution/fps/frame count and audio stream properties. | Container/stream properties reported by FFprobe for a readable file; audio stream present or absent. | Actual audible speech, music, perceptual quality, creator intent. Missing/variable stream fields, VFR FPS ambiguity, source versus normalized file differences. | Duration and acquisition quality gates; denominators for rates. |
| Transcript | Mono 16 kHz WAV from normalized video; faster-whisper `base` CPU/int8, beam 5, VAD. `audio.text` and `{start,end,text}` segments, rounded to 0.001 s. Silent video gives empty text/segments. | Approximate recognized speech and segment intervals, conditional on model and audio quality. | Word-level timing, speaker identity, speech versus music inventory, exact first spoken word, language certainty, silence duration, rhetorical function. VAD can remove quiet speech; music/noise/accent/crosstalk, hallucination and segment drift can corrupt text/timing. | Evidence for later speech and intent models; rough speaking rate and first recognized segment. |
| Scene boundaries | PySceneDetect `ContentDetector(threshold=27)` on normalized video; `scenes[]` has scene number, start/end/duration and legacy field `cut_timestamp_seconds` (null for first scene). | Heuristic content-change boundaries at frame resolution. The field name does not establish an editorial cut. | Jump cut, hard cut versus transition, B-roll, shot intent. Motion, flashes, lighting, overlays and small changes can trigger or hide boundaries; threshold is fixed. | Candidate change locations; detected-scene duration statistics with caveats. |
| OCR/on-screen text | RapidOCR on sampled frames at nominal 2 FPS; confidence ≥0.6. Tracks same casefolded/space-normalized text when box IoU ≥0.5. `on_screen_text[]` has text, quadrilateral box, confidence, appearance/disappearance seconds. | Text recovered in sampled frames, with approximate visible interval and location. | Captions, headline, CTA, language, text animation, semantic role. Brief text may fall between samples; stylized/low contrast/occluded text fails; moving boxes or recognition variation split tracks; onset/offset quantized by sampling. | Candidate text regions and transcript alignment for a future caption classifier; approximate text occupancy. |
| Motion events | Dense Farnebäck flow on nominal 8 FPS samples, downscaled to ≤480px width. Heuristics use flow magnitude, coverage, coherence, radial alignment and direction stability. Pipeline returns `{type,start_seconds,end_seconds,confidence}` for `camera_pan`, `camera_zoom`, `camera_shake`, `local_motion`, `general_motion`, `unknown`. | Measurable pixel displacement and heuristic motion pattern over an approximate interval. | Camera action with certainty, intentional zoom, punch-in, subject movement, speed ramp, pattern interrupt. A `camera_zoom` type is a flow label, not verified visible zoom. Hard cuts, overlays, texture, compression, low light and moving objects confound flow; confidence is heuristic, not calibrated probability. | Motion density, candidate continuous scale/translation events, subject/camera separation research. |

The pipeline calls scene, OCR and motion analysis after normalizing video. It transcribes only when FFprobe found an audio codec. No semantic technique detector, music classifier, audio-event classifier, speech-to-speaker visual alignment or visual object detector is present. Existing recommendations may interpret these observations; that does not validate an ontology label.

### Measured generated-media sanity check

I ran the unchanged pipeline on the existing test generator's **silent** clip and scored independently known properties: 4.0-second duration, 640×360 resolution, no audio stream, one color-change boundary at 2.0 seconds, and `VIDEO TEST` rendered throughout. The pipeline reported one boundary at exactly 2.0 seconds (precision 1/1, recall 1/1, matched timing error 0.0 seconds), one OCR track with exact normalized text and interval 0.0–4.0 seconds (text and temporal precision/recall 1/1, temporal IoU 1.0), and matching metadata. It also produced one `local_motion` event, but that type was **not scored**: the moving rectangle establishes visible motion, not an independently annotated flow category. The empty transcript is expected for this silent clip. These are sanity results for a single deliberately easy synthetic sample, not estimates for real videos. The opt-in media tests also passed with the sine-wave audio variant; no spoken-word ground truth exists there, so transcript accuracy was not measured.

## Offline evaluation harness

Run `cd backend && python -m intelligence.evaluation.v8_baseline intelligence/evaluation/fixtures/synthetic_manifest.json`. Manifest version 1 lists local `analysis` and `truth` JSON paths relative to itself, with optional per-fixture `boundary_tolerance_seconds` (default 0.25) and `minimum_interval_iou` (default 0.5). Paths cannot escape the manifest directory. Use output from the unchanged `analyze_file` as the analysis JSON. Ground truth should be independently checked against media; omit any signal that was not annotated. An explicitly empty list means a checked negative. Keep each creator/source group separate in future train/test splits; this tool makes no train/test split.

Metrics are **per fixture and per signal**, never averaged into an overall score:

| Truth key | Metric | Matching rule and interpretation |
| --- | --- | --- |
| `scene_boundaries_seconds` | Precision, recall, mean absolute matched timing error | One-to-one nearest matching within timestamp tolerance. First-scene null is excluded. No matched event means timing error is null. |
| `on_screen_text` | Normalized exact-token text precision/recall; text-and-time precision/recall and mean interval IoU | Casefold + Unicode word tokens; one-to-one matching. Temporal match requires identical normalized tokens and IoU ≥ configured threshold. No semantic text classification. |
| `transcript` | Token-level word error rate (`edit_distance / reference_tokens`); segment endpoint mean absolute error | Tokenization uses Unicode word groups. Empty reference gives null WER. Endpoint error is reported **only** when supplied reference segments and model segments have equal count and matching normalized text in order. Otherwise timestamp error is null, because pairing is ambiguous. |
| `motion_events` | Type-aware interval precision/recall and mean IoU | One-to-one match requires same V8 heuristic type and minimum interval IoU. This measures agreement with manually marked low-level motion patterns, not technique accuracy. |
| `metadata` | Exact matches or numeric absolute error/within-tolerance | Ground truth keys use dotted paths; numeric expectations are `{ "value": number, "tolerance": number }`. Source-video metadata is evaluated, not normalized-file metadata. |

Precision/recall are null when their denominator is zero. A predicted event against an empty exhaustive truth has precision 0 and recall null. These nulls should stay missing in any later aggregation. The pairing algorithm is deterministic greedy by match quality, so dense ambiguous events may need a more formal assignment algorithm if real evaluation shows collisions. Intervals require positive duration. The example manifest is a calculation self-check; its scores are **not** detector baseline results.

## V8 → V9 ontology coverage gap

“Direct support” here means the V8 output can itself justify the ontology definition. For all rows below, direct support is **none**. “Partial evidence” means a low-level observation may help a future detector, not that a V8 label exists.

| Frozen ontology IDs | Existing useful evidence | Required V9 intelligence / caveat |
| --- | --- | --- |
| `hook.question`, `hook.bold_claim`, `hook.curiosity_gap`, `hook.result_first`, `hook.problem_statement`, `hook.story_open` | Transcript and/or OCR text; scene timing may locate the opening. | Opening-window understanding, language/pragmatic classification and often visual context. A transcript question is not necessarily a hook. |
| `hook.visual` | Scene/OCR/motion timestamps. | Salience and opening intent from visual content; none of these signals establishes it. |
| `format.talking_head`, `format.tutorial`, `format.product_demo`, `format.storytime`, `format.listicle`, `format.reaction`, `format.before_after`, `format.screen_recording`, `format.interview` | Transcript, OCR, scene and motion context. | Video-level scene/subject/action and discourse understanding; audible or transcribed speech does not establish a visible talking head. Talking-head and screen-recording labels need visual recognition. |
| `editing.jump_cut`, `editing.punch_in` | Scene boundaries; motion may indicate changes around a boundary. | Adjacent-frame/shot comparison and continuity or crop recognition. A boundary is neither label. |
| `editing.zoom` | `camera_zoom` flow type is **partial evidence** for continuous scale change. | Validate real scale change within one shot and reject object motion/flow artifacts; V8 flow type alone is unsafe. |
| `editing.transition`, `editing.b_roll`, `editing.speed_ramp`, `editing.freeze_frame`, `editing.split_screen`, `editing.picture_in_picture` | Scene/motion signals can nominate intervals; OCR may indicate overlays. | Temporal visual reasoning, frame composition and/or playback analysis. Hard cut is not `editing.transition`; no direct B-roll evidence. |
| `text.captions`, `text.headline`, `text.keyword_emphasis`, `text.text_reveal` | OCR intervals/boxes are **partial evidence** of text presence; transcript can support caption alignment. | Text-role classifier; captions require alignment to speech. Visual styling and reveal order need sampled-frame visual analysis. |
| `structure.pattern_interrupt` | Scene/motion changes can nominate candidate times. | Established-pattern context plus meaningful audiovisual change. One scene change is insufficient. |
| `audio.voiceover`, `audio.direct_speech` | Transcript establishes possible speech only. | Speaker visibility/lip alignment and source attribution. |
| `audio.music`, `audio.sound_effect`, `audio.beat_synced_edit` | Audio stream metadata only; scene timestamps for possible edit points. | Audio event/music/beat analysis, then audiovisual alignment for beat-synced edits. No present music detection. |
| `cta.verbal`, `cta.visual`, `cta.follow`, `cta.save`, `cta.comment`, `cta.share`, `cta.product` | Transcript/OCR can contain candidate words. | Request/intent classification, modality and action target. Mere keyword occurrence is not a CTA. |
| `visual.face_to_camera`, `visual.product_foreground`, `visual.close_up`, `visual.wide_shot`, `visual.screen_content`, `visual.multiple_subjects` | Metadata resolution and low-level scene/motion boundaries only. | Frame-level object/person/layout recognition and shot-scale understanding. |

The same absence applies to V8.5 structure roles (`hook`, `setup`, `problem`, `explanation`, `demonstration`, `proof`, `payoff`, `cta`, `other`): V8 has no role segmentation. No ontology ID should be inferred by renaming a V8 signal.

## Cheap numeric feature opportunities from existing output

### High confidence from current outputs

These are high confidence **calculations over returned detector output**, not claims that the detector found every real event. `scene_count` counts returned scene intervals. `scene_boundaries_first_5_seconds` counts non-null legacy `cut_timestamp_seconds` values in an explicitly truncated first-five-second window. `average_detected_scene_duration_seconds` averages returned scene durations, with null when no valid intervals exist. None measures verified editorial shots or cuts. The frozen V8.5 example name `cuts_first_5_seconds` remains an example in the contract document; this research pass recommends the narrower `scene_boundaries_first_5_seconds` name for any future feature registry, without changing the contract.

### Requires calibration

| Candidate | Current computable proxy | What must be checked |
| --- | --- | --- |
| `words_per_second` | ASR token count divided by explicitly named video duration or recognized-speech span. | ASR errors, language tokenization and denominator choice. It is a recognized-word rate, not verified speech rate. |
| `first_text_time` | Earliest OCR track appearance. | Sampling at nominal 2 FPS, missed/false text and timing quantization. |
| `text_presence_ratio` | Union of OCR track intervals divided by video duration. | False/missed tracks, box tracking splits and interval bias; simultaneous tracks must not double count. |
| `motion_density` | Union of V8 flow-event intervals divided by video duration. | Flow false positives from scene changes and artifacts, and false negatives for subtle movement. |
| `first_recognized_segment_time` | Earliest ASR segment start. | Segment timing, VAD omission and false transcription; it is not first spoken word time. |

### Not currently supportable

`cuts_first_5_seconds` as a true editorial-cut count, `average_shot_length_seconds` as real shot length, and exact `first_spoken_word_time` need cut/shot or word-level evidence the current pipeline does not produce. `silence_gaps` as acoustic silence needs actual audio/VAD interval evidence; gaps between ASR segments are only untranscribed gaps and can contain speech or music. These names must not be populated by silently relabelling current scene or transcript outputs.

No production derived features were added. Before V9 adoption, specify window endpoints, null handling, producer version, and whether the feature means a measured property or a detector-output statistic.

## Blind spots and recommended V9 priorities

The largest gaps are audio beyond speech, visual subjects/actions/composition, and temporal intent. The present sample cannot quantify real-world precision or recall; a licensed, diverse, human-labelled media set is necessary. Recommended V9 order:

1. **Low-level calibration:** establish representative human truth and measure ASR, OCR, scene-boundary and flow coverage, precision, timing and failure modes. Keep detector outputs separate from true cuts, captions and camera actions.
2. **Audio/visual evidence expansion:** add and evaluate audio event/music/silence evidence, word timing where needed, and visual person/subject/layout and shot-continuity evidence. These are prerequisites for many labels; do not infer them from current transcript or metadata alone.
3. **Narrow semantic classifiers:** with labelled examples and calibrated inputs, test specific claims such as caption alignment, true edit type or visible talking head. Report per-label precision/recall and abstention.
4. **Higher-level semantic reasoning:** only after lower-level evidence and annotation agreement are credible, evaluate hook, CTA, format and structure roles with temporal context. Do not treat an isolated question, keyword or scene change as intent.
