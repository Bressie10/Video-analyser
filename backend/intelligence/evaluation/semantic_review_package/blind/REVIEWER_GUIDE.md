# Independent semantic video review

Ontology version: **1.1.0**.

Watch the complete assigned video with audio before annotating. Record what is
actually visible or audible. Do not consult any prior annotation or analysis
before submitting your review.

## Annotation instructions

- Make one reviewer JSON per reviewer per video. Fill every `null` in the template,
  then validate it with the offline validator. Submit the file before discussing it
  with another reviewer. Separate reviewer files must remain unchanged.
- Record each technique or primary structure role with `present`, `absent`, or
  `uncertain`, confidence from 0 to 1, and a short evidence note. Uncertainty is valid.
  An omitted technique counts as absent only when its category coverage is `complete`.
- Set category coverage independently for hook, format, editing, text, audio, CTA,
  and visual, plus primary structure: `complete` means the full video and category
  were assessed; `partial` means only some relevant material was assessable;
  `unavailable` means it could not be assessed. Explain limitations in evidence notes.
- Record reviewer ID or pseudonym, reviewer type, full-video and audio flags,
  blind-review flag, whether you had previously seen ContentMetric outputs,
  and a timezone-aware review timestamp. An earlier unrelated output exposure
  should be disclosed even if this annotation was otherwise blind.
- Use the frozen definitions below literally. `whole_video` is a video-level
  property; the supporting action need not persist throughout the runtime unless
  that definition itself requires substantial or main-format coverage.
- A product or service shown in use can support `format.product_demo`. A visible
  request, including request text, can support `cta.visual`. A request for a
  product-related action such as a visit or purchase can support `cta.product`.
- Record each physical CTA request once in `cta_events` and attach all independently
  supported CTA ontology labels to that event. Multiple labels may describe one event.
- Use one primary narrative structure role at a time. Different roles may touch
  at a boundary but must not substantially overlap. Leave gaps when evidence is
  insufficient; do not use `other` simply to fill a gap.

## Timestamp conventions

- Use seconds from the first video frame; intervals are `[start_seconds, end_seconds)`.
  Record the earliest and latest supported boundaries, with `start < end`.
- Point techniques use `start_seconds` and a null `end_seconds`. Whole-video
  formats use null for both timestamps. An absent annotation has null timestamps.
  An uncertain annotation may be left unlocalized with null timestamps.
- Do not extend an interval through a gap on assumption alone. A claim seen in
  one frame does not establish a continuous action between distant frames.
- For audible techniques, listen to source audio. Spoken words shown as captions
  establish visible text, while an audible request can separately support speech.

## Generic examples

- A clip showing a person operating a coffee grinder can support
  `format.product_demo` even if that clip occupies only part of the video.
- A card saying “Visit the store” can support `cta.visual` and `cta.product`
  on one CTA event; an audible “Visit the store” can also support `cta.verbal`.
- A narrator describing a recipe step, followed by a request to save the recipe,
  may have an explanation interval followed by a CTA interval, with no overlap.

### Illustrative JSON entry shapes

Add records to the template arrays using these fields. These examples describe
an imaginary coffee video and are not expected answers for any assigned source.

```json
{
  "items": [
    {"technique_id": "format.product_demo", "status": "present",
     "confidence": 0.8, "evidence_note": "A grinder is operated on screen.",
     "start_seconds": null, "end_seconds": null}
  ],
  "cta_events": [
    {"event_id": "request-1", "status": "present", "confidence": 0.9,
     "evidence_note": "A card asks viewers to visit the store.",
     "requested_action": "Visit the store",
     "start_seconds": 8.0, "end_seconds": 9.0,
     "labels": [
       {"technique_id": "cta.visual", "status": "present",
        "confidence": 0.9, "evidence_note": "The request is visible.",
        "start_seconds": 8.0, "end_seconds": 9.0}
     ]}
  ],
  "structure": [
    {"role": "cta", "status": "present", "confidence": 0.9,
     "evidence_note": "The closing segment requests a visit.",
     "start_seconds": 8.0, "end_seconds": 9.0}
  ]
}
```

## Controlled primary structure roles

`hook`, `setup`, `problem`, `explanation`, `demonstration`, `proof`, `payoff`, `cta`, `other`

## Frozen ontology definitions

### hook

| ID | Observation kind | Definition |
| --- | --- | --- |
| `hook.question` | interval | Opens with a spoken or displayed question. |
| `hook.bold_claim` | interval | Opens with an assertive claim intended to draw attention. |
| `hook.curiosity_gap` | interval | Opens by withholding an answer or outcome explicitly promised later. |
| `hook.result_first` | interval | Shows or states an outcome before explaining how it happened. |
| `hook.problem_statement` | interval | Opens by naming a problem to be addressed. |
| `hook.story_open` | interval | Opens by setting up a narrated event or situation. |
| `hook.visual` | interval | Opens with a salient visual before or alongside explanatory content. |

### format

| ID | Observation kind | Definition |
| --- | --- | --- |
| `format.talking_head` | whole_video | Speaker addresses the camera for a substantial part of the video. |
| `format.tutorial` | whole_video | Explains a process or teaches a skill in steps. |
| `format.product_demo` | whole_video | Shows a product or service in use. |
| `format.storytime` | whole_video | Narrates an event as the main format. |
| `format.listicle` | whole_video | Presents numbered or clearly enumerated items. |
| `format.reaction` | whole_video | Responds to another piece of content or event. |
| `format.before_after` | whole_video | Compares a state before and after a change. |
| `format.screen_recording` | whole_video | Recorded screen is a principal visual source. |
| `format.interview` | whole_video | Question and answer exchange is a principal format. |

### editing

| ID | Observation kind | Definition |
| --- | --- | --- |
| `editing.jump_cut` | point | Abrupt cut within a continuous subject or setup. |
| `editing.punch_in` | point | Abrupt reframing to a closer crop of the same shot. |
| `editing.zoom` | interval | Continuous visible change in framing scale within a shot. |
| `editing.transition` | interval | Deliberate non-hard-cut visual transition between shots or scenes. |
| `editing.b_roll` | interval | Supporting footage overlays or interrupts the main action. |
| `editing.speed_ramp` | interval | Playback speed visibly changes within a shot. |
| `editing.freeze_frame` | interval | A held still frame interrupts moving footage. |
| `editing.split_screen` | interval | Two or more distinct visual regions display simultaneously. |
| `editing.picture_in_picture` | interval | A smaller inset moving image overlays a principal image. |

### text

| ID | Observation kind | Definition |
| --- | --- | --- |
| `text.captions` | interval | On-screen text follows spoken words. |
| `text.headline` | interval | Prominent on-screen title summarizes or frames the content. |
| `text.keyword_emphasis` | interval | Selected words receive distinct visual emphasis. |
| `text.text_reveal` | interval | Text appears progressively as an editing device. |

### structure

| ID | Observation kind | Definition |
| --- | --- | --- |
| `structure.pattern_interrupt` | point | Presentation changes abruptly to interrupt an established visual or audio pattern. |

### audio

| ID | Observation kind | Definition |
| --- | --- | --- |
| `audio.voiceover` | interval | Speech is heard without the speaker speaking on screen. |
| `audio.direct_speech` | interval | A visible person speaks in the scene. |
| `audio.music` | interval | Music is audible during the interval. |
| `audio.sound_effect` | interval | Non-speech, non-music effect is audible. |
| `audio.beat_synced_edit` | point | A visual edit coincides with an audible musical beat. |

### cta

| ID | Observation kind | Definition |
| --- | --- | --- |
| `cta.verbal` | interval | Spoken request asks the viewer to act. |
| `cta.visual` | interval | Visible request asks the viewer to act. |
| `cta.follow` | interval | Requests a follow or subscription. |
| `cta.save` | interval | Requests that the viewer save the content. |
| `cta.comment` | interval | Requests a comment. |
| `cta.share` | interval | Requests that the viewer share the content. |
| `cta.product` | interval | Requests a product-related action such as a visit or purchase. |

### visual

| ID | Observation kind | Definition |
| --- | --- | --- |
| `visual.face_to_camera` | interval | A person faces the camera directly. |
| `visual.product_foreground` | interval | Product is prominent in the frame. |
| `visual.close_up` | interval | Subject fills much of the frame. |
| `visual.wide_shot` | interval | Frame shows broad surroundings around the subject. |
| `visual.screen_content` | interval | A device or software screen is visible. |
| `visual.multiple_subjects` | interval | Two or more principal subjects share the frame. |
