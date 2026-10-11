# V9 Stage 4.1: motion classification quality audit

Production motion behavior and thresholds remain unchanged. This is a deliberately stratified 54-event audit of the Stage 4 raw stream and stabilized variants. Private media-derived frame sequences were reviewed outside Git; only derived observations are committed.

**Evidence limit:** One AI visual review of short frame sequences, with no independent human adjudication. First-pass sheets hid detector classes, but final labels were recorded after the detector classes were inspected. These are provisional sample agreement figures, not population precision or ground truth.

## Sampling and review

Nine events per detector class across 11 videos. Sources 04, 07, 09 and 12 were prioritized; all four events from 09 were included. Within class/source quotas, events were spread across duration and confidence. Frames were read from the original pilot MP4s at Stage 4 raw sample timestamps. Each review sequence spans 0.75 s before and after its anchor, with denser central frames. Labels apply to that context, not necessarily every moment of a long baseline event. The four 09 events were also inspected at native 30 fps. Nearby events in the same footage are not independent.

## Per-class sample precision

| Detector class | Correct / determinate | Uncertain | Sample precision |
| --- | ---: | ---: | ---: |
| camera_pan | 1 / 9 | 0 | 0.111 |
| camera_zoom | 0 / 9 | 0 | 0.000 |
| camera_shake | 0 / 9 | 0 | 0.000 |
| local_motion | 8 / 9 | 0 | 0.889 |
| general_motion | 0 / 9 | 0 | 0.000 |
| unknown | — / 8 | 1 | — (no exact semantic target) |

An exact match maps `local_motion` to `local_subject_motion` and `general_motion` to `general_scene_motion`. Uncertain labels are excluded from precision denominators. Unknown has no exact semantic target, so its composition is shown in the confusion matrix.

## Confusion matrix

Rows are detector classes; columns are reviewed classes.

| Detector | pan | zoom | shake | local subject | general scene | no meaningful | uncertain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| camera_pan | 1 | 0 | 0 | 6 | 1 | 1 | 0 |
| camera_zoom | 2 | 0 | 0 | 3 | 1 | 3 | 0 |
| camera_shake | 0 | 0 | 0 | 5 | 0 | 4 | 0 |
| local_motion | 0 | 0 | 0 | 8 | 0 | 1 | 0 |
| general_motion | 0 | 0 | 0 | 4 | 0 | 5 | 0 |
| unknown | 0 | 0 | 0 | 6 | 1 | 1 | 1 |

## Confidence distribution

| Group | n | Mean | Median | Min–max |
| --- | ---: | ---: | ---: | ---: |
| Exact semantic matches | 9 | 0.701 | 0.667 | 0.562–0.931 |
| Incorrect semantic predictions | 36 | 0.785 | 0.796 | 0.591–0.967 |
| Unknown with visually valid motion | 7 | 0.482 | 0.482 | 0.457–0.517 |
| Unknown with no meaningful motion | 1 | 0.526 | 0.526 | 0.526–0.526 |

## Stabilization outcomes on reviewed events

“Same class” means the detector label overlaps the raw sample support; “any event” means some event overlaps that support. This distinction matters when singleton suppression relabels a valid short event. Obvious noise is the `no_meaningful_motion` review class, chiefly edit and graphic transitions.

| Configuration | Valid same class aligned | Valid any event aligned | Noise class absent | Noise no event |
| --- | ---: | ---: | ---: | ---: |
| nonoverlap_only | 20/38 | 38/38 | 8/15 | 0/15 |
| short_run_suppression | 28/38 | 38/38 | 8/15 | 4/15 |
| min_0.5 | 17/38 | 25/38 | 14/15 | 10/15 |
| unknown_as_gap | 22/38 | 31/38 | 8/15 | 5/15 |

Nonoverlap-only emits all 1,351 original labels. Its 8/15 noise-class absences are timing shifts from clipping, **not removals**; the same shift leaves only 20/38 valid labels aligned with their raw samples. The other variants rebuild intervals from raw sample cells. “Any event” can retain motion with an incorrect class, so it is not semantic accuracy.

## Video 09 and decision implications

All four 09 baseline events are `general_motion` at abrupt scale edits. Each has exactly one classified motion sample between null/no-motion samples; the current event builder exports a roughly 0.267 s interval around it. A-B-A singleton suppression absorbs all four. Native-frame review showed discrete edit jumps, with no continuous camera move.

| Audit ID | Interval s | Motion sample s | Before / after | Reviewed | Survives singleton rule |
| --- | --- | --- | --- | --- | --- |
| M001 | [10.133, 10.4] | 10.267 | None / None | no_meaningful_motion | False |
| M029 | [14.0, 14.267] | 14.133 | None / None | no_meaningful_motion | False |
| M037 | [6.0, 6.267] | 6.133 | None / None | no_meaningful_motion | False |
| M049 | [2.133, 2.4] | 2.267 | None / None | no_meaningful_motion | False |

The sampled `camera_pan`, `camera_zoom` and `camera_shake` labels are not reliable enough to expose as trusted downstream semantics. Of three visually clear pan events, only M006 was labeled pan; M034 and M052 were labeled zoom. There were no visually confirmed zoom or shake events in this sample. Incorrect semantic predictions had higher mean detector confidence (0.785) than exact matches (0.701), so confidence does not resolve this sample.

Unknown is mixed: 7/9 sampled unknown events showed valid motion, one was an edit artifact, and one was uncertain. Treating unknown as a gap removes its label but can discard useful motion evidence; uncertainty is the safer interpretation pending reviewed ground truth. Singleton suppression retained all three visually clear pan events under their existing detector labels in this sample; the 0.5 s filter removed M052. This tiny camera-truth subset cannot establish general retention of useful short camera events.

No stabilization strategy or threshold is selected for production.

## Reviewed records

| ID | Video | Interval s | Detector | Confidence | Reviewed | Note |
| --- | --- | --- | --- | ---: | --- | --- |
| M001 | 09 | [10.133, 10.4] | general_motion | 0.896 | no_meaningful_motion | Abrupt crowd scale edit; no continuous camera move. |
| M002 | 07 | [42.267, 42.8] | unknown | 0.457 | local_subject_motion | Hands manipulating helmet; background fixed. |
| M003 | 05 | [21.889, 22.422] | local_motion | 0.803 | local_subject_motion | Person's head and body move in a fixed frame. |
| M004 | 12 | [29.467, 29.733] | general_motion | 0.634 | local_subject_motion | Speaker gestures while background stays fixed. |
| M005 | 07 | [81.067, 82.4] | local_motion | 0.562 | local_subject_motion | Gloved hands move around a machine. |
| M006 | 06 | [31.2, 32.0] | camera_pan | 0.931 | camera_pan | Room features translate together through a continuous camera move. |
| M007 | 03 | [36.036, 36.303] | camera_shake | 0.774 | local_subject_motion | Speaker shifts in a fixed shot. |
| M008 | 04 | [22.5, 22.75] | local_motion | 0.667 | local_subject_motion | Hands and hair move; background remains fixed. |
| M009 | 04 | [46.25, 47.5] | camera_zoom | 0.825 | local_subject_motion | Subject and foam move in a mostly fixed shot; opening scale change is a cut. |
| M010 | 12 | [18.0, 29.6] | local_motion | 0.651 | local_subject_motion | Talking head gestures in a fixed frame. |
| M011 | 07 | [9.6, 10.0] | camera_pan | 0.859 | no_meaningful_motion | Graphic layout and text switch; no continuous scene motion. |
| M012 | 05 | [41.241, 41.508] | unknown | 0.491 | general_scene_motion | Several dancers move through the scene. |
| M013 | 07 | [15.733, 16.0] | local_motion | 0.591 | no_meaningful_motion | Helmet graphic switches layout and text without continuous physical motion. |
| M014 | 07 | [106.267, 106.8] | local_motion | 0.734 | local_subject_motion | Hands tape a stationary box. |
| M015 | 07 | [103.467, 103.733] | camera_shake | 0.772 | no_meaningful_motion | Abrupt edit between packing shots at the event. |
| M016 | 04 | [129.375, 129.625] | unknown | 0.482 | local_subject_motion | People and hands move inside a fixed vehicle view. |
| M017 | 04 | [52.625, 52.875] | camera_shake | 0.717 | local_subject_motion | Water and a person move in a fixed shot. |
| M018 | 12 | [31.2, 32.4] | local_motion | 0.621 | local_subject_motion | Talking head gestures; background fixed. |
| M019 | 04 | [2.5, 3.0] | general_motion | 0.856 | no_meaningful_motion | Abrupt change in framing is an edit rather than continuous motion. |
| M020 | 04 | [76.875, 77.25] | unknown | 0.517 | local_subject_motion | Two people gesture within a fixed frame. |
| M021 | 07 | [130.8, 131.067] | camera_pan | 0.854 | local_subject_motion | Riders and motorcycle move while the background remains mostly fixed. |
| M022 | 04 | [48.75, 49.0] | general_motion | 0.795 | local_subject_motion | Foam and hands move in the foreground. |
| M023 | 04 | [50.75, 51.25] | camera_zoom | 0.807 | general_scene_motion | Passing cars and foreground washing both move; no continuous zoom. |
| M024 | 04 | [119.125, 119.5] | camera_pan | 0.808 | local_subject_motion | Hands and recipient move in a fixed vehicle view. |
| M025 | 07 | [39.467, 40.4] | camera_pan | 0.758 | general_scene_motion | Multiple workers move across the factory view. |
| M026 | 07 | [22.0, 22.267] | camera_shake | 0.711 | no_meaningful_motion | City shot is stable; overlay text changes after a cut. |
| M027 | 07 | [0.933, 1.2] | general_motion | 0.633 | local_subject_motion | Rider adjusts helmet visor in a fixed frame. |
| M028 | 07 | [110.533, 110.8] | camera_zoom | 0.774 | local_subject_motion | Presenter gestures in a fixed warehouse shot. |
| M029 | 09 | [14.0, 14.267] | general_motion | 0.967 | no_meaningful_motion | Abrupt crowd scale edit; no continuous camera move. |
| M030 | 04 | [137.125, 137.375] | unknown | 0.526 | no_meaningful_motion | Hard edit between scenes at the event. |
| M031 | 05 | [5.739, 6.006] | camera_shake | 0.711 | local_subject_motion | Woman speaks and moves in a fixed shot. |
| M032 | 03 | [35.903, 36.17] | camera_pan | 0.631 | local_subject_motion | Speaker shifts in a fixed shot. |
| M033 | 04 | [100.375, 101.125] | camera_pan | 0.884 | local_subject_motion | Hands work at the vehicle; background fixed. |
| M034 | 06 | [3.867, 4.4] | camera_zoom | 0.792 | camera_pan | Room features translate together through a continuous camera move. |
| M035 | 07 | [29.733, 30.0] | unknown | 0.519 | uncertain | Factory view drifts slightly, but the short interval and nearby cut do not establish pan. |
| M036 | 04 | [91.875, 92.125] | camera_shake | 0.801 | no_meaningful_motion | Hard cut from person to hands at the event. |
| M037 | 09 | [6.0, 6.267] | general_motion | 0.957 | no_meaningful_motion | Abrupt crowd scale edit; no continuous camera move. |
| M038 | 04 | [134.875, 135.125] | camera_zoom | 0.752 | no_meaningful_motion | Rapid edits between unrelated shots, not a continuous zoom. |
| M039 | 04 | [107.0, 107.75] | local_motion | 0.688 | local_subject_motion | Person and hands move in a fixed vehicle shot. |
| M040 | 04 | [48.875, 49.125] | camera_pan | 0.874 | local_subject_motion | Foam, hands and person move; background fixed. |
| M041 | 07 | [113.333, 114.667] | camera_zoom | 0.765 | no_meaningful_motion | Office view remains nearly fixed; nearby changes are cuts. |
| M042 | 04 | [42.75, 43.0] | camera_pan | 0.799 | local_subject_motion | Washing and people move within a fixed frame. |
| M043 | 04 | [121.625, 122.375] | unknown | 0.489 | local_subject_motion | People and hands move inside a fixed vehicle view. |
| M044 | 07 | [67.467, 67.733] | unknown | 0.472 | local_subject_motion | Machine component moves locally; the following scene is a cut. |
| M045 | 11 | [44.044, 44.294] | camera_zoom | 0.738 | no_meaningful_motion | Hard edit between unrelated scenes at the event. |
| M046 | 10 | [20.667, 21.333] | local_motion | 0.653 | local_subject_motion | Hands and face move in a fixed view. |
| M047 | 04 | [16.75, 17.0] | camera_shake | 0.681 | local_subject_motion | Hands and hair move in a fixed shot. |
| M048 | 01 | [23.6, 24.267] | general_motion | 0.688 | local_subject_motion | Presenter speaks and gestures; background fixed. |
| M049 | 09 | [2.133, 2.4] | general_motion | 0.892 | no_meaningful_motion | Abrupt crowd scale edit; no continuous camera move. |
| M050 | 08 | [12.8, 13.067] | unknown | 0.469 | local_subject_motion | Person manipulates product in a fixed shot. |
| M051 | 04 | [123.25, 123.5] | camera_zoom | 0.838 | local_subject_motion | Hands and people move within a fixed vehicle frame. |
| M052 | 07 | [60.8, 61.2] | camera_zoom | 0.812 | camera_pan | Camera tracks rider while the background translates across the frame. |
| M053 | 04 | [23.625, 24.0] | camera_shake | 0.802 | local_subject_motion | Hands and hair move in a fixed shot. |
| M054 | 07 | [118.133, 118.4] | camera_shake | 0.798 | no_meaningful_motion | Hard edit between two office shots at the event. |
