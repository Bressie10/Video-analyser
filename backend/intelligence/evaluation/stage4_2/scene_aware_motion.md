# V9 Stage 4.2: scene-aware motion experiment

Offline replay only. Production scene and motion detection, `_classify_optical_flow()` and all thresholds are unchanged. Every video was normalized with the production helper; production `detect_scenes()` at threshold 27 was rerun and matched the stored pilot scene output exactly. Repaired reference scene truth was never used to alter motion output.

The Stage 4.1 54-event visual review is provisional: one AI review of short private frame sequences, with no independent human adjudication. These are selected-sample retention figures, not motion precision or population estimates.

## Method

When a production cut falls after the previous sampled frame and at or before the current sampled frame, that optical-flow pair is skipped. Its sample cell becomes a gap. The current post-cut frame becomes the next previous frame, and direction history is cleared. An active event therefore ends at its last pre-cut sample cell. Singleton suppression cannot bridge a protected cut gap. `unknown` remains an event; no duration filter is applied.

The two non-scene comparators are the exact Stage 4 variants. Clipping-only can shift a class interval off the raw sample that generated it. All results use half-open event intervals; audit survival is measured against the raw class support from Stage 4.1.

## Eleven-video output structure

| Variant | Events | Events/min | Overlap s | Median s | Mean s | Runtime covered % | Counts pan/zoom/shake/local/general/unknown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| nonoverlap_only | 1351 | 121.104 | 0.000 | 0.250 | 0.464 | 93.692 | 151/107/76/280/460/277 |
| one_sample_suppression_only | 735 | 65.886 | 0.000 | 0.375 | 0.845 | 92.741 | 104/62/45/129/250/145 |
| scene_aware_reset_only | 1160 | 103.983 | 0.000 | 0.250 | 0.499 | 86.551 | 149/101/30/284/387/209 |
| scene_aware_reset_plus_suppression | 824 | 73.863 | 0.000 | 0.400 | 0.704 | 86.629 | 114/69/22/213/267/139 |

The combined variant can produce more events than singleton suppression alone: scene gaps split runs, and clearing direction history changes some later class labels.

## Per-video output structure

Counts use pan/zoom/shake/local/general/unknown order.

| Video | Variant | Events | Events/min | Overlap s | Median s | Mean s | Covered % | Type counts |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| **01** | nonoverlap_only | 56 | 117.073 | 0.000 | 0.200 | 0.512 | 100.000 | 1/1/2/11/24/17 |
| **01** | one_sample_suppression_only | 26 | 54.355 | 0.000 | 0.800 | 1.104 | 100.000 | 1/1/1/5/10/8 |
| **01** | scene_aware_reset_only | 53 | 110.801 | 0.000 | 0.267 | 0.521 | 96.286 | 1/1/2/11/23/15 |
| **01** | scene_aware_reset_plus_suppression | 29 | 60.627 | 0.000 | 0.667 | 0.953 | 96.286 | 1/1/1/6/12/8 |
| **03** | nonoverlap_only | 102 | 112.113 | 0.000 | 0.266 | 0.516 | 96.333 | 4/3/3/45/35/12 |
| **03** | one_sample_suppression_only | 37 | 40.668 | 0.000 | 0.400 | 1.385 | 93.887 | 2/3/1/14/12/5 |
| **03** | scene_aware_reset_only | 76 | 83.535 | 0.000 | 0.334 | 0.618 | 86.070 | 2/3/1/45/19/6 |
| **03** | scene_aware_reset_plus_suppression | 59 | 64.850 | 0.000 | 0.534 | 0.794 | 85.823 | 2/3/1/35/13/5 |
| **04** | nonoverlap_only | 394 | 170.686 | 0.000 | 0.250 | 0.352 | 100.000 | 76/67/24/12/132/83 |
| **04** | one_sample_suppression_only | 228 | 98.773 | 0.000 | 0.375 | 0.607 | 100.000 | 46/34/13/6/81/48 |
| **04** | scene_aware_reset_only | 363 | 157.256 | 0.000 | 0.250 | 0.359 | 94.043 | 75/63/10/12/122/81 |
| **04** | scene_aware_reset_plus_suppression | 235 | 101.805 | 0.000 | 0.375 | 0.554 | 94.043 | 49/38/7/7/84/50 |
| **05** | nonoverlap_only | 147 | 175.173 | 0.000 | 0.134 | 0.314 | 91.717 | 11/4/11/27/50/44 |
| **05** | one_sample_suppression_only | 77 | 91.757 | 0.000 | 0.267 | 0.588 | 89.862 | 6/1/7/18/24/21 |
| **05** | scene_aware_reset_only | 128 | 152.531 | 0.000 | 0.134 | 0.316 | 80.325 | 13/4/4/27/44/36 |
| **05** | scene_aware_reset_plus_suppression | 90 | 107.249 | 0.000 | 0.400 | 0.446 | 79.795 | 8/2/3/21/32/24 |
| **06** | nonoverlap_only | 50 | 60.281 | 0.000 | 0.267 | 0.747 | 75.016 | 9/10/2/9/16/4 |
| **06** | one_sample_suppression_only | 37 | 44.608 | 0.000 | 0.400 | 0.987 | 73.411 | 8/7/2/4/13/3 |
| **06** | scene_aware_reset_only | 47 | 56.664 | 0.000 | 0.400 | 0.738 | 69.663 | 10/10/0/9/15/3 |
| **06** | scene_aware_reset_plus_suppression | 38 | 45.814 | 0.000 | 0.400 | 0.916 | 69.930 | 10/8/0/5/12/3 |
| **07** | nonoverlap_only | 350 | 133.616 | 0.000 | 0.134 | 0.444 | 98.898 | 46/20/30/78/117/59 |
| **07** | one_sample_suppression_only | 219 | 83.606 | 0.000 | 0.267 | 0.704 | 98.135 | 37/14/18/41/72/37 |
| **07** | scene_aware_reset_only | 295 | 112.619 | 0.000 | 0.266 | 0.488 | 91.691 | 44/19/10/77/95/50 |
| **07** | scene_aware_reset_plus_suppression | 218 | 83.224 | 0.000 | 0.400 | 0.663 | 91.945 | 40/16/8/54/64/36 |
| **08** | nonoverlap_only | 79 | 172.573 | 0.000 | 0.134 | 0.338 | 97.089 | 1/0/3/21/29/25 |
| **08** | one_sample_suppression_only | 38 | 83.010 | 0.000 | 0.400 | 0.698 | 96.601 | 1/0/2/12/13/10 |
| **08** | scene_aware_reset_only | 66 | 144.175 | 0.000 | 0.267 | 0.352 | 84.484 | 1/0/2/21/30/12 |
| **08** | scene_aware_reset_plus_suppression | 47 | 102.670 | 0.000 | 0.400 | 0.497 | 84.968 | 1/0/1/16/22/7 |
| **09** | nonoverlap_only | 4 | 14.516 | 0.000 | 0.267 | 0.267 | 6.460 | 0/0/0/0/4/0 |
| **09** | one_sample_suppression_only | 0 | 0.000 | 0.000 | — | — | 0.000 | 0/0/0/0/0/0 |
| **09** | scene_aware_reset_only | 0 | 0.000 | 0.000 | — | — | 0.000 | 0/0/0/0/0/0 |
| **09** | scene_aware_reset_plus_suppression | 0 | 0.000 | 0.000 | — | — | 0.000 | 0/0/0/0/0/0 |
| **10** | nonoverlap_only | 77 | 149.676 | 0.000 | 0.134 | 0.390 | 97.192 | 0/0/0/34/19/24 |
| **10** | one_sample_suppression_only | 30 | 58.315 | 0.000 | 0.466 | 0.991 | 96.327 | 0/0/0/11/11/8 |
| **10** | scene_aware_reset_only | 55 | 106.911 | 0.000 | 0.400 | 0.475 | 84.667 | 0/0/0/34/18/3 |
| **10** | scene_aware_reset_plus_suppression | 42 | 81.641 | 0.000 | 0.533 | 0.625 | 85.102 | 0/0/0/27/12/3 |
| **11** | nonoverlap_only | 77 | 57.964 | 0.000 | 0.250 | 0.973 | 94.035 | 3/2/1/35/27/9 |
| **11** | one_sample_suppression_only | 36 | 27.100 | 0.000 | 0.250 | 2.065 | 93.249 | 3/2/1/14/11/5 |
| **11** | scene_aware_reset_only | 62 | 46.672 | 0.000 | 0.689 | 1.132 | 88.070 | 3/1/1/40/14/3 |
| **11** | scene_aware_reset_plus_suppression | 59 | 44.414 | 0.000 | 0.501 | 1.192 | 88.227 | 3/1/1/38/13/3 |
| **12** | nonoverlap_only | 15 | 25.210 | 0.000 | 0.400 | 2.380 | 100.000 | 0/0/0/8/7/0 |
| **12** | one_sample_suppression_only | 7 | 11.765 | 0.000 | 0.267 | 5.100 | 100.000 | 0/0/0/4/3/0 |
| **12** | scene_aware_reset_only | 15 | 25.210 | 0.000 | 0.267 | 2.380 | 100.000 | 0/0/0/8/7/0 |
| **12** | scene_aware_reset_plus_suppression | 7 | 11.765 | 0.000 | 0.267 | 5.100 | 100.000 | 0/0/0/4/3/0 |

## Scene reset coverage

| Video | Production cuts | Flow pairs skipped | Other sample labels changed after resets |
| --- | ---: | ---: | ---: |
| **01** | 8 | 8 | 0 |
| **03** | 33 | 33 | 3 |
| **04** | 66 | 66 | 21 |
| **05** | 38 | 38 | 6 |
| **06** | 14 | 14 | 3 |
| **07** | 73 | 73 | 19 |
| **08** | 24 | 24 | 1 |
| **09** | 5 | 5 | 0 |
| **10** | 26 | 26 | 0 |
| **11** | 32 | 32 | 0 |
| **12** | 0 | 0 | 0 |

## Stage 4.1 reviewed audit retention

Visually valid excludes `uncertain` and `no_meaningful_motion`. Noise means reviewed `no_meaningful_motion`. Same-class and any-event retention are separately counted on each raw class support interval. A different overlapping class does not prove that the motion meaning was retained.

| Variant | Valid same class | Valid any event | Noise same class absent | Noise no event |
| --- | ---: | ---: | ---: | ---: |
| nonoverlap_only | 20/38 | 38/38 | 8/15 | 0/15 |
| one_sample_suppression_only | 28/38 | 38/38 | 8/15 | 4/15 |
| scene_aware_reset_only | 31/38 | 36/38 | 9/15 | 8/15 |
| scene_aware_reset_plus_suppression | 25/38 | 36/38 | 9/15 | 8/15 |

Clipping-only changes no event count, so its absent labels are timing misalignment rather than event removal.

## Audit by original detector class

Each cell is `valid same class / valid any event / noise no event`; denominators appear in the first columns. Reviewed labels remain fixed from Stage 4.1.

| Detector class | Valid | Noise | Nonoverlap | Singleton | Scene reset | Scene reset + singleton |
| --- | ---: | ---: | --- | --- | --- | --- |
| camera_pan | 8 | 1 | 4 / 8 / 0 | 8 / 8 / 0 | 7 / 8 / 0 | 7 / 8 / 0 |
| camera_zoom | 6 | 3 | 4 / 6 / 0 | 4 / 6 / 0 | 5 / 5 / 1 | 4 / 5 / 1 |
| camera_shake | 5 | 4 | 1 / 5 / 0 | 2 / 5 / 0 | 1 / 5 / 2 | 1 / 5 / 2 |
| local_motion | 8 | 1 | 7 / 8 / 0 | 7 / 8 / 0 | 8 / 8 / 0 | 7 / 8 / 0 |
| general_motion | 4 | 5 | 1 / 4 / 0 | 1 / 4 / 4 | 4 / 4 / 4 | 2 / 4 / 4 |
| unknown | 7 | 1 | 3 / 7 / 0 | 6 / 7 / 0 | 6 / 6 / 1 | 4 / 6 / 1 |

## Video 09: all four reviewed events

| ID | Baseline class | Production cut(s) on raw support | Nonoverlap same/any | Singleton same/any | Scene same/any | Combined same/any |
| --- | --- | --- | --- | --- | --- | --- |
| M001 | general_motion | [10.2] | True/True | False/False | False/False | False/False |
| M029 | general_motion | [14.067] | True/True | False/False | False/False | False/False |
| M037 | general_motion | [6.1] | True/True | False/False | False/False | False/False |
| M049 | general_motion | [2.2] | True/True | False/False | False/False | False/False |

## Cut attribution and limits

**Yes, production-detected boundary crossings account for a meaningful subset of semantic failures in this selected sample:** 10 of 36 incorrect semantic predictions (27.778%). They intersect 8 of 14 semantic predictions reviewed as no meaningful motion. The remaining semantic failures do not cross a production-detected cut, so scene reset alone cannot make the motion classes trustworthy.

Across the pilot, 319 production scene boundaries caused 319 skipped flow pairs, and clearing direction history changed 53 additional non-cut sample labels. In the reviewed set, scene reset removes all four 09 edit artifacts and leaves no event on 8/15 no-meaningful-motion examples, but also removes 2/38 visually valid examples (M044, M051). Adding singleton suppression does not remove more reviewed no-meaningful-motion examples or recover those valid examples; it changes same-class retention. No variant is selected for production.

Co-occurrence with a production scene boundary is an attribution signal, not proof that every such prediction was caused by an editorial cut. The reviewed sample cannot detect newly introduced errors outside its intervals.

Per-video metrics, the replayed sample stream, cut timestamps, skipped pairs, and all 54 audit survival rows are in the JSON.
