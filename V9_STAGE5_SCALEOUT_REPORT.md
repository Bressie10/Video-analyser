# V9 Stage 5 semantic scale-out — frozen Stage 5.4

## Outcome and scope

The seven remaining pilots (`03 05 06 07 09 10 11`) were attempted with the
Stage 5.4 `run_one` inference function from base
`a784d8d6195b79e28075eabc133d9c4d4632212a`. Four produced validated
candidates; `07`, `09` and `11` produced complete model checkpoints but failed
frozen contract validation. Together with the unchanged `01 04 08 12`
artifacts, **8 of 11 have accepted Stage 5.4 outputs**. No rejected draft was
silently repaired, counted as validated, or used to tune the model.

The `stage5_4_scaleout.py` entry point calls the unchanged Stage 5.4 inference
function. Pass 1 and Pass 2 prompts, ontology `1.1.0`, frame selection,
evidence-ledger rules, CTA and structure logic, and thresholds were not tuned.
The requested and reported model was `gpt-6-sol`; prompt SHA-256 values remain
`b6b6e28ddc272a547dd71e04bb587e58926cb0d420e0c7bc52b1bbed73dd57ce`
and `117850c2e1705d0fbb58c08a438cef7e1022c7054ed04f6f8ceeca402428dd27`.
Each accepted candidate records response IDs, prompt hashes, model, SDK
version, analyzer and validation commits, content hash, frame hashes, source
pipeline commit, ledger and report. The seven new checkpoints preserve all
model responses, including the two rejected drafts. The four original
candidate files remain byte-for-byte unchanged.

## Minimal runtime defects found during scale-out

1. `06` initially failed the privacy guard because the visual rationale said a
   text panel “shares the image” with people. The guard interpreted `shares`
   as a performance metric. The guard now permits that narrow grammatical use
   while still rejecting a shares count. The saved model response was
   revalidated without regeneration or text edits.
2. `09` initially failed final-frame decoding: the container/audio duration was
   16.669s, while the video stream had 496 frames at 30 fps (16.533s). The
   existing final-frame plan requested 16.569s. Extraction now clamps an
   out-of-stream frame index to the last actual video frame and records its
   actual timestamp. Frame selection policy and semantic inference did not
   change. An initial local `09` candidate was excluded because it ran before
   the fix was committed, leaving incomplete code provenance. A fresh run
   against commit `699c4c6` failed the frozen structure-role contract. No
   candidate was selected on the basis of its semantic output.

## Contract and quality audit

The machine-readable [corpus audit](backend/intelligence/evaluation/stage5_4/corpus_audit.json)
reconstructs ledger and synthesis validation for every accepted candidate.
It checks ontology IDs, original evidence references and ledger support,
performance and motion exclusion, source-audio labels, incompatible primary
structure overlaps, CTA event/label mapping, format decision support, frame
coverage, impossible timestamps, and embedded private media or credential
markers. All eight accepted candidates passed: **zero evidence-ledger failures
and zero validation/contract failures**. Every accepted source has at least one
explicit uncertainty. Selected frames number 11–29 per accepted video; the
largest individual supplied-frame gap is 7.292s (`04`). Sparse frames and
transcript/OCR errors remain material limits, even when a contract passes.

Two rejected drafts failed exactly at the existing no-unsupported-gap
gate: `07` assigned a proof interval across 30.600–31.190s without cited
atomic coverage (0.590s); `11` assigned an interval across 40.290–40.541s
(0.251s). `09` assigned `ledger:0:0` to both hook and payoff, which the frozen
primary-role validator rejects. These are **contract failures**, not accuracy measurements. Their
frame coverage was measured, but their draft labels are excluded from the
validated distributions below. The raw drafts and validator failure records
are retained for future review.

## Eleven-video reading guide

The entries for `07`, `09` and `11` describe rejected, unvalidated drafts. Other
entries describe accepted candidates. These are concise descriptions of model
outputs and supplied evidence, not independently verified video annotations.

| Video | Hook; formats; main structure | CTA events | Key observations and uncertainty |
| --- | --- | --- | --- |
| `01` | Bold fragrance-dupe claim; product demo; hook → explanation/demonstration/proof → CTA | Grab/buy fragrance, 25.68–28.40s | Bottle, box, captions and laptop product page; exact inhalation and camera address between stills unverified. |
| `03` | Bold motivational claim and visual opening; no supported format; hook → setup/problem → explanation → payoff | None established | Speaker, water imagery, captions and close views; OCR/transcript conflict and exact cuts unknown. No format decision deserves inference from sparse camera-address evidence alone. |
| `04` | Transformation curiosity gap; before/after and product demo; hook → setup → demonstrations/payoffs → two CTAs | “Wear/spread love” at 132.16–133.16s; join/buy at 136.16–138.50s | Clipper, groomed state, leg care and closing captions; change process and purchased item identity remain uncertain. |
| `05` | Dance-career claim and graphic; no supported format; hook → setup/explanation → CTA → explanation → CTAs | In-person course, online license, become an instructor, end card: four events | Benefit headlines, camera-facing speaker and product foreground; German OCR differs from transcript and continuous exercise is unproved. Four CTA events merit later human inspection. |
| `06` | Real-estate-career question and coastline graphic; no supported format; hook → setup/explanation → proof/payoff → CTA | Apply/join at 34.93–40.00s and join at 40.00–42.08s | Coastline B-roll, split screen, people and tablet; location and spoken organization name uncertain. Adjacent requests merit later human inspection. |
| `07` **rejected** | Draft: visual/problem hook; listicle; hook → setup/problem → explanation/proof/payoff | Draft has none | Helmet displays, text headings, captions and B-roll; a proof span crosses a 0.590s unsupported ledger gap. No accepted semantic report. Product and certification claims remain unverified. |
| `08` | Visual skincare hook; product demo; hook → demonstrations → CTA | Quiz overlay and separate end card | Products/tools and “Your Personal Plan is Ready!” text; sparse frames do not prove dispensing, button press or before/after result. |
| `09` **rejected** | Draft: visual follower-count opening; no supported format; hook → payoff | Draft has none | A suited person appears among phone-holding people, with changing follower counts; the draft assigns one atomic item to both hook and payoff. No accepted semantic report. Crowd movement and speech delivery are unknown. |
| `10` | Claimed age/appearance result; product demo; hook → setup/explanation/problem/payoff → two CTAs | Try skincare product at 24.1–27.0s; take quiz at 28.0–30.9s | Routine headline, captions and product containers; product spelling differs in transcript/OCR and the claimed skin result is unverified. |
| `11` **rejected** | Draft: perfume-brand claim/story opening; product demo; hook → setup/problem/explanation/payoff | Draft has none | Dropper/spray B-roll and price/cost captions; an interval crosses a 0.251s unsupported ledger gap. No accepted semantic report. The end-card URL is not an explicit CTA. |
| `12` | Career question; talking head and listicle; hook → setup/explanation → CTA | Request course catalog at 32.16–35.44s | Repeated speaker-to-camera frames; speaker title/institution transcription and the 14.32–20.32s visual gap remain uncertain. |

## Descriptive corpus statistics

These counts cover **the eight accepted candidates only**. They count finding
instances for techniques and structure segments for roles; multiple labels
can belong to one physical CTA. They are neither prevalence estimates for a
larger population nor performance or accuracy results.

| Dimension | Distribution |
| --- | --- |
| Formats | product demo 4; before/after 1; listicle 1; talking head 1 |
| Hook techniques | visual 4; bold claim 4; question 2; result first 1; curiosity gap 1 |
| CTA technique instances | product 13; visual 12; verbal 9 |
| Structure-role segments | explanation 15; CTA 11; demonstration 11; hook 8; payoff 6; setup 6; proof 4; problem 2 |
| Uncertainty | 8/8 accepted videos; 31 explicit synthesis statements |
| Evidence-ledger failures | 0 in accepted candidates; not scored for rejected drafts |
| Validation/contract failures | 3 rejected drafts (`07`, `09`, `11`); 0 in accepted candidates |

## Validation status and V9 recommendation

Stage 5.1 truth was **AI-assisted, non-blind and provisional**. No independent
human semantic evaluation was completed. Stage 5.4 therefore remains
**provisionally validated**; no population semantic-accuracy estimate exists.
The [independent-review workflow](backend/intelligence/evaluation/semantic_review_package/README.md)
remains available for future evaluation. No semantic technique is connected
to ad performance in this work.

Proceed with V9 work that does not rely on trusted semantic accuracy. Keep
Stage 5.4 as an offline, provenance-bearing, provisional candidate. Gate or
abstain on failed sources (`07`, `09`, `11`), preserve their checkpoints for later
human evaluation, and do not use rejected drafts or corpus distributions to
choose production recommendation behavior. No merge, deployment or tag is in
scope.
