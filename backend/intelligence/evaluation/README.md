# V8.5 human evaluation, guideline version 1.0.0

This directory is offline dataset tooling. It does not acquire media or run a detector. The frozen `Annotation`, `AnnotationDataset`, and ontology definitions are authoritative; the guidance below sets human decision rules within those meanings. All times are seconds from the first displayed frame, including opening black or silence. Use half-open intervals `[start, end)`; a point uses `end_seconds: null`; a whole-video format uses `start_seconds: 0` and `end_seconds: null`. Record to the nearest visible/audible 0.1 second, without implying frame precision. End an interval at the first frame where the evidence stops. Break it across real gaps; do not bridge a missing shot, muted passage, or hidden overlay. Simultaneous labels are allowed when each independently meets its definition. Do not stretch a label to fit a structure segment.

For every row below: **yes** is a positive example, **no** is a clear negative, **edge** resolves a borderline case, and **error** is a common mistake. Timing uses the observation kind in the ontology: `I` means visible/audible duration, `P` means the event instant, and `W` means one whole-video observation. Repeated intervals or points may be separate records. Every technique permits overlap with other techniques; the row's overlap note gives useful co-labeling guidance.

## Technique decision table

| ID (kind) | Definition and yes | No | Edge, timing, overlap, error |
|---|---|---|---|
| `hook.question` (I) | Opening spoken or displayed question; “Why did this fail?” | A question first asked midway. | Start at first question sound/text, end at question completion/removal. A rhetorical question counts. May coexist with curiosity gap only if an answer is explicitly promised later. Error: labeling every question as a hook. |
| `hook.bold_claim` (I) | Opening assertive attention claim; “This is the fastest method.” | Ordinary neutral introduction. | Claim need not be true. Mark utterance/text duration; may coexist with result first if it actually states an outcome before explanation. Error: treating all confident speech as bold. |
| `hook.curiosity_gap` (I) | Opening explicitly withholds an answer/outcome promised later; “Wait until you see what happened.” | An unanswered question with no promise of later resolution. | Promise may be spoken or displayed; mark promise duration. May coexist with question, but the question alone is insufficient. Error: inferring suspense from music alone. |
| `hook.result_first` (I) | Opening shows/states outcome before how; finished makeover before steps. | Showing the initial problem only. | Mark the outcome reveal, not the later explanation. May coexist with bold claim when outcome is assertively claimed. Error: calling any product shot a result. |
| `hook.problem_statement` (I) | Opening names an issue to address; “My audio kept clipping.” | Generic topic title, “Audio tips.” | Mark the issue statement; may coexist with question if phrased as a question. Error: assigning to a later problem section. |
| `hook.story_open` (I) | Opening sets up a narrated event/situation; “Yesterday I missed the train…” | A generic hypothetical example in a tutorial. | Mark opening setup until narration turns to next function. Can overlap a problem statement. Error: assuming all first-person speech is a story. |
| `hook.visual` (I) | Salient opening visual before/with explanation; unexpected result in first shot. | Routine talking face on first frame. | Mark only salient opening visual while it remains the draw; can overlap any verbal hook. Error: labeling every first frame. |
| `format.talking_head` (W) | Speaker addresses camera for a substantial part; solo explanation to lens. | Interviewee answering an off-camera host, without address to viewer. | Substantial means a principal presentation mode, not a single glance. Can coexist with tutorial. Error: equating any visible face with this format. |
| `format.tutorial` (W) | Process or skill taught in steps; three stages of editing a clip. | One product feature shown without teaching steps. | Steps can be verbal or visual. May coexist with screen recording/product demo. Error: calling general advice a tutorial. |
| `format.product_demo` (W) | Product/service shown in use; app workflow demonstrated. | Static product beauty shot. | Principal segment must show use. Can coexist with tutorial. Error: treating a mere mention as demo. |
| `format.storytime` (W) | Narrated event is main format; recounting a customer encounter. | One anecdote within a broader how-to. | First-person not required. Can coexist with talking head. Error: marking any sequential explanation. |
| `format.listicle` (W) | Numbered or clearly enumerated items organize video; “three fixes.” | Steps of one process without item-list framing. | Spoken enumeration counts without graphics. Can coexist with tutorial. Error: counting incidental “first” as list format. |
| `format.reaction` (W) | Responds to another content/event; commentary on viewed clip. | Original demonstration with no response target. | Target can be off-screen if identifiable. Can coexist with picture-in-picture. Error: treating surprise facial expression alone as reaction format. |
| `format.before_after` (W) | Compares states before and after change. | Final result alone. | Explicit comparison can be sequential, not necessarily split screen. Can coexist with product demo. Error: inferring a missing before state. |
| `format.screen_recording` (W) | Recorded screen is a principal visual source; software walkthrough. | Brief phone screen insert. | A camera filming a display may instead have `visual.screen_content`; use W only when recorded screen is principal. Can coexist with tutorial. Error: treating every visible screen as format. |
| `format.interview` (W) | Question-answer exchange is principal format; host asks guest. | Solo speaker uses rhetorical questions. | Remote participants count. Can coexist with talking head only if substantial direct-to-camera presentation also occurs. Error: inferring interview from two faces alone. |
| `editing.jump_cut` (P) | Abrupt cut within continuous subject/setup; sentence jumps in same framing. | Dissolve or cut to different B-roll scene. | Place point at first frame after cut. Can coincide with punch in if crop also jumps. Error: calling every hard cut a jump cut. |
| `editing.punch_in` (P) | Abrupt closer crop of same shot. | Smooth scale change. | Point at new closer framing; may coincide with jump cut. Error: calling a new camera angle a punch in. |
| `editing.zoom` (I) | Continuous visible scale change in a shot. | One-frame crop jump. | Mark first to last scale change; can coexist with speech/B-roll. Error: conflating movement toward camera with an edited zoom when scale evidence is unclear. |
| `editing.transition` (I) | Deliberate non-hard-cut transition between shots/scenes; dissolve or wipe. | Straight hard cut. | Mark visible transition duration; may coexist with B-roll at boundary. Error: labeling jump cuts as transitions. |
| `editing.b_roll` (I) | Supporting footage overlays/interrupts main action; cutaway showing the described workspace. | Main product demonstration footage itself. | Mark supporting shot duration, including overlay. Can coexist with captions/voiceover. Error: treating every non-face shot as B-roll. |
| `editing.speed_ramp` (I) | Playback speed visibly changes within shot. | Entire shot at uniformly fast speed. | Mark ramped portion, not whole shot. Can coexist with music. Error: guessing speed changes from fast action alone. |
| `editing.freeze_frame` (I) | Held still interrupts moving footage. | Static photo that was never moving footage. | Mark held portion. Can coexist with headline. Error: treating naturally still subject as freeze. |
| `editing.split_screen` (I) | Distinct visual regions shown simultaneously side by side. | One smaller inset over dominant image. | Mark simultaneous layout duration; picture-in-picture takes precedence for a small inset, though both may apply if genuinely distinct split regions also exist. Error: labeling a text panel as second video region. |
| `editing.picture_in_picture` (I) | Smaller inset moving image overlays principal image. | Equal side-by-side panels. | Mark duration both images are visible; may coexist with reaction. Error: counting static logo as moving inset. |
| `text.captions` (I) | On-screen words track spoken words. | Topic title unrelated to exact speech. | Mark from first matching word to last matching word, split at substantial gaps. May coexist with headline if separately displayed. Error: treating all text as captions. |
| `text.headline` (I) | Prominent title frames/summarizes content; “How to fix audio.” | Word-by-word speech subtitles. | Mark title visibility; can coexist with captions. Error: treating every large subtitle as headline. |
| `text.keyword_emphasis` (I) | Selected words visually distinguished; one word changes color. | Uniform subtitle styling. | Mark emphasized word visibility; can overlap captions. Error: labeling every caption word. |
| `text.text_reveal` (I) | Text appears progressively as an editing device. | Entire sentence appears at once. | Mark from first incremental appearance through last reveal, not extended static hold. Can overlap captions/headline. Error: treating ordinary caption updates as a deliberate reveal. |
| `structure.pattern_interrupt` (P) | Abrupt change breaks an established visual/audio pattern; sudden silence after repeated beat/cuts. | An ordinary cut in a varied montage. | Point at disruptive change; requires evidence of prior pattern. Can coincide with edit/sound effect. Error: calling every cut an interrupt. |
| `audio.voiceover` (I) | Speech heard while speaker is not speaking on screen; narration over demo. | Visible speaker delivering words in scene. | Mark heard speech. For mixed cuts, split where visibility/speaking relation changes. Can overlap music. Error: deciding from microphone quality. |
| `audio.direct_speech` (I) | Visible person speaks in scene. | Narration over silent visible person. | Mouth sync or clear in-scene delivery required; mark audible speech. Can overlap music. Error: assuming any visible person is the speaker. |
| `audio.music` (I) | Music audibly present. | Only rhythmic speech or ambient noise. | Mark actual audible spans, including under speech. Error: inferring music from beat-synced visuals without listening. |
| `audio.sound_effect` (I) | Distinct non-speech/non-music effect; added whoosh. | Ordinary speech or musical note. | Natural sound can count if presented as effect; mark audible duration. Can overlap transition. Error: calling all ambient noise an effect. |
| `audio.beat_synced_edit` (P) | Visual edit lands on audible music beat. | Cut without audible beat. | Point at edit; confirm by listening, not visual rhythm alone. Can coincide with jump cut. Error: marking every music-backed cut. |
| `cta.verbal` (I) | Spoken request to viewer to act; “Save this.” | Mere statement “I saved it.” | Mark request utterance. Co-label with action label (`cta.save` here); verbal describes channel, action label describes requested behavior. Error: using verbal as substitute for action. |
| `cta.visual` (I) | Visible request to viewer to act; “Follow for more” card. | Passive handle/logo. | Mark display duration. Co-label with action label. Error: counting all branded text. |
| `cta.follow` (I) | Requests follow/subscription. | “I follow this creator.” | Mark request duration in either channel; can overlap verbal/visual. Error: requiring exact word “follow” when “subscribe” clearly asks same action. |
| `cta.save` (I) | Requests saving content. | “Save the file” as an instructional software step. | Mark viewer-directed request; co-label channel. Error: confusing task instruction with platform CTA. |
| `cta.comment` (I) | Requests a viewer comment. | Creator reads an existing comment. | Mark request; can coexist with another action request. Error: labeling any comment mention. |
| `cta.share` (I) | Requests sharing content. | Creator describes sharing their own file. | Mark request; co-label channel. Error: mistaking narrative action for CTA. |
| `cta.product` (I) | Requests product action, e.g. visit, book, buy. | Product mentioned without viewer request. | Mark request; co-label channel. Error: calling every product demonstration a CTA. |
| `visual.face_to_camera` (I) | Person faces lens directly. | Profile view addressing interviewer. | Mark visible facing interval; may coexist with talking-head W but neither implies the other. Error: using this as a format label. |
| `visual.product_foreground` (I) | Product prominent in frame. | Small background product/logo. | Mark prominence duration; can coexist with demo. Error: labeling mere presence. |
| `visual.close_up` (I) | Subject fills much of frame. | Medium shot with surroundings. | Mark close framing duration; can coexist with face to camera. Error: inferring close-up from portrait aspect ratio. |
| `visual.wide_shot` (I) | Broad surroundings shown around subject. | Tight shot of one object. | Mark wide framing duration; can overlap multiple subjects. Error: confusing landscape frame with wide shot. |
| `visual.screen_content` (I) | Device/software screen visible. | Screen only mentioned in speech. | Mark visibility; can coexist with screen-recording W. Error: assuming any tutorial shows screen. |
| `visual.multiple_subjects` (I) | Two or more principal subjects share frame. | One subject plus background passerby. | Mark simultaneous principal presence; can coexist with split screen. Error: counting incidental faces. |

## Structure roles

Structure describes **what a span does for the viewer**, independently of technique labels. A `hook` role is the opening attention function even when none of the seven hook techniques is present; a hook technique may occur inside an opening `setup` or `problem` role if its mechanism is present. Label every discernible function, including `other` for material serving none of the named roles. Adjacent roles may touch exactly at a boundary. A role may recur. Genuine functions may overlap: annotate both intervals and add a note explaining the dual purpose. Do not force a single exclusive timeline or duplicate a role solely to fill gaps.

| Role | Include | Exclude / boundary |
|---|---|---|
| `hook` | Opening attention bid, from first attention cue until it turns to context/content. | A later surprising moment; end at functional shift, even if opening visual remains on screen. |
| `setup` | Context, actors, goal, prerequisites needed to understand what follows. | The actual problem or step explanation; boundary at first explicit shift. |
| `problem` | States or illustrates the obstacle, need, or tension. | Generic context; stop when solution begins. |
| `explanation` | Describes why/how/what without actively showing execution. | Active execution is demonstration; stop when showing starts. |
| `demonstration` | Performs process or shows product/technique in use. | Outcome evidence alone is proof; start on action, end when action ceases. |
| `proof` | Offers evidence that a claim/result is credible: test, measured comparison, testimonial, or verified outcome. | Performing the action without evidence of efficacy. A demonstration may overlap proof when the live result is itself evidence; note why. |
| `payoff` | Resolves an earlier promise, question, tension, or transformation with an answer/outcome. | Any merely pleasant ending or generic recap. Start at resolution reveal; a result-first opening is not automatically payoff unless it resolves a previously established expectation within the video. |
| `cta` | Direct viewer request to act, spoken or visible. | Passive branding or creator's own action; may overlap a payoff if resolution includes a request. |
| `other` | Meaningful remaining content, e.g. unrelated greeting or outro without CTA. | Do not use to hide uncertain roles; note uncertainty and seek review. |

## Annotation workflow

1. Register source identity and media reference in `manifest.json`. Assign stable opaque source and creator/near-duplicate group refs before labeling. Keep media outside Git. Capture duration and media provenance in private source inventory; record only safe local/external reference in manifest. Set source-level split before analysis, with one group entirely in one partition.
2. First annotator watches once without pausing for primary structure/format, then replays for interval and point labels. Record precise boundaries, uncertain decisions in `note` or annotation `notes`, and numeric values only from a documented measurement method. Do not infer absent labels from an unchecked category.
3. For each technique category, mark complete only after every applicable technique in that category was checked throughout the full video. An empty technique list plus complete category is a reviewed negative. Leave incomplete categories unlisted. `structure_complete` has the same meaning for all structure roles. For numeric fields, declare measured, unavailable (with reason), or not applicable (with reason). Measured status requires exactly one value, unit, optional window, and evidence refs. Use a pre-agreed field catalogue and units in the annotation project; do not mix definitions across annotators.
4. Independent second annotator works without seeing first labels on a stratified subset and all difficult cases. They validate media, timing, coverage, and numeric provenance. Run `agreement`; inspect per-label disagreement and intervals, then adjudicate from media. Preserve original annotations and write adjudication notes separately rather than silently overwriting independent evidence.
5. Review unresolved cases with a third annotator. Log source, competing labels, relevant time, rationale, and guideline version. If a guideline is clarified, version it and consider re-reviewing affected prior sources. Keep disagreement statistics on the independent pass, before adjudication.

## Dataset files and commands

```
dataset/
  manifest.json                 # sources and source-level split_assignments
  annotations/
    source-001__annotator-a.json # one Annotation contract per file
```

`manifest.json` has `sources: [{reference_id, media_ref, notes}]` and `split_assignments: [{source_ref, partition, group_ref}]`. `media_ref` may be an access-controlled URI or local path; loading does not fetch it. Do not commit private URLs, secrets, or copyrighted media. The loader requires unique manifest source refs, one split/group per source, exactly matched annotated sources, unique annotation refs, and at most one annotation per annotator per source. The frozen `AnnotationDataset` checks source identity and group leakage. Files parse with the frozen Pydantic contracts, so unsupported versions, unknown labels, bad timing, and missing required values fail.

From `backend/`:

```
python -m intelligence.evaluation validate intelligence/evaluation/examples
python -m intelligence.evaluation summary intelligence/evaluation/examples
python -m intelligence.evaluation agreement intelligence/evaluation/examples
```

`summary` gives label observation counts, coverage denominators, incomplete categories and structures, numeric status counts, split counts, and multi-annotator sources. A zero label count is meaningful only where that category was fully checked. `agreement` compares all annotator pairs on shared sources. Presence agreement is reported **only when both declare the category complete**. For interval labels and each structure role it reports union-of-spans IoU (`null` when both are absent); for point labels it reports ordered one-to-one absolute time distances plus unmatched count. It does not score numeric fields, adjudication quality, severity of disagreements, or truth. No universal accuracy value is produced. Aggregate rates need denominators, prevalence, and a documented tolerance policy; high agreement on rare negatives alone is weak evidence.

## Selection plan for first 60–100 sources

Build a stratified sampling sheet *before* viewing labels or outcomes. Target roughly 10–15 sources per principal format across talking head, tutorial, product demo, storytime, reaction, screen recording, interview, and before/after, allowing multi-format sources and then checking actual coverage. Cross-balance fast/slow cuts, heavy/light editing, captions/no captions, music/no music, and strong/weak opening hooks. Include ordinary, low-production and weak-performing material; do not sample only viral or polished clips. Vary platform, length, topic, creator size and language only where annotators can judge reliably. Track those sampling dimensions outside the annotation contract.

Sample by creator and concept group, not by individual upload. Put all versions, reposts, clips from one recording, near-identical scripts, and same creator into one `group_ref` and one split. Prefer creator-disjoint train/validation/test (e.g. 60/20/20) and audit apparent duplicates manually; the CLI enforces declared groups but cannot discover semantic or perceptual duplicates. Reserve test sources before rule tuning. Double-label at least 20–30%, including every rare format and ambiguous pair; expand overlap where disagreement is concentrated. Do not acquire videos in this workstream.

## Known contract boundaries

The frozen schema allows structure gaps/overlaps, repeated spans, and annotations in categories not declared complete. This supports partial work, but human review must enforce the coverage meaning above. It has no adjudication-status field, per-source creator identity, or numeric feature catalogue; use a separate review log/inventory and manifest `group_ref`. The CLI checks declared group leakage only; a wrong group assignment remains a curation risk.
