# V9 Stage 4.3 — motion evidence contract experiment

Offline only. Production detection, API, schema and classifier thresholds are unchanged. The 54-event Stage 4.1 review is a small, selected, provisional visual audit; these figures do not establish population accuracy. One uncertain case is excluded from precision/recall.

## Method

Flow is replayed with production normalization, 8 FPS sampling and unchanged Farnebäck/classifier settings. Every raw label, confidence and timestamp must match Stage 4. Stage 4.2 production scene detector cuts were independently reproduced against stored pilot output at threshold 27. Crossing flow cells are excluded in both simplified variants; the reset variant also clears direction history. Singleton suppression runs within cut-separated segments before class mapping; originally null flow cells remain gaps and cannot become evidence. Local motion survives only with the existing classifier's local label and coverage at most 0.4. All other non-null classes, including unknown, become `motion_present`. That neutral state says only that measured flow was present; it does not imply camera movement or a motion technique.

Each sample carries mean flow magnitude over all pixels, active pixel coverage, active median vector magnitude, coherence and radial alignment. Event descriptors are means over contributing flow cells. These are observations, not inferred pan/zoom/shake semantics. Null values mean no active pixels. Simplified events omit legacy semantic confidence; raw samples retain it for provenance. Event intervals are half-open. JSON contains every sample, event, audit row and per-video metric.

## Eleven-video output structure

| Variant | Events | Events/min | Median s | Mean s | Runtime coverage % | Overlap s | Counts by type |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| existing_semantic_output | 1351 | 121.104 | 0.267 | 0.589 | 93.692 | 169.244 | camera_pan 151, camera_shake 76, camera_zoom 107, general_motion 460, local_motion 280, unknown 277 |
| nonoverlap_plus_singleton | 735 | 65.886 | 0.375 | 0.845 | 92.741 | 0.000 | camera_pan 104, camera_shake 45, camera_zoom 62, general_motion 250, local_motion 129, unknown 145 |
| scene_aware_plus_singleton | 824 | 73.863 | 0.400 | 0.704 | 86.629 | 0.000 | camera_pan 114, camera_shake 22, camera_zoom 69, general_motion 267, local_motion 213, unknown 139 |
| simplified_cut_mask_plus_singleton | 562 | 50.378 | 0.667 | 1.029 | 86.391 | 0.000 | local_motion 257, motion_present 305 |
| simplified_scene_reset_plus_singleton | 562 | 50.378 | 0.667 | 1.029 | 86.391 | 0.000 | local_motion 257, motion_present 305 |

## Reviewed sample

Presence precision/recall treats all visually meaningful review classes as positive and `no_meaningful_motion` as negative. Local precision/recall uses `local_subject_motion` as positive and all other determinate labels as negative. A retained event overlaps the raw class support by more than 1 ms; it need not retain the exact original semantic class.

| Variant | Valid retained / 38 | Presence precision | Presence recall | No-motion false positives / 15 | Local precision | Local recall | Cut-associated no-motion retained |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| existing_semantic_output | 38 | 0.717 | 1.000 | 15 | 0.786 | 0.344 | 9/9 |
| nonoverlap_plus_singleton | 38 | 0.776 | 1.000 | 11 | 0.727 | 0.250 | 5/9 |
| scene_aware_plus_singleton | 36 | 0.837 | 0.947 | 7 | 0.900 | 0.281 | 1/9 |
| simplified_cut_mask_plus_singleton | 36 | 0.837 | 0.947 | 7 | 0.875 | 0.219 | 1/9 |
| simplified_scene_reset_plus_singleton | 36 | 0.837 | 0.947 | 7 | 0.875 | 0.219 | 1/9 |

## Focus videos

| Video | Variant | Events | Coverage % | Median s | Mean s | Overlap s |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 04 | existing_semantic_output | 394 | 100.000 | 0.375 | 0.476 | 49.125 |
| 04 | nonoverlap_plus_singleton | 228 | 100.000 | 0.375 | 0.607 | 0.000 |
| 04 | scene_aware_plus_singleton | 235 | 94.043 | 0.375 | 0.554 | 0.000 |
| 04 | simplified_cut_mask_plus_singleton | 82 | 94.043 | 1.500 | 1.588 | 0.000 |
| 04 | simplified_scene_reset_plus_singleton | 82 | 94.043 | 1.500 | 1.588 | 0.000 |
| 07 | existing_semantic_output | 350 | 98.898 | 0.267 | 0.573 | 44.942 |
| 07 | nonoverlap_plus_singleton | 219 | 98.135 | 0.267 | 0.704 | 0.000 |
| 07 | scene_aware_plus_singleton | 218 | 91.945 | 0.400 | 0.663 | 0.000 |
| 07 | simplified_cut_mask_plus_singleton | 153 | 91.606 | 0.534 | 0.941 | 0.000 |
| 07 | simplified_scene_reset_plus_singleton | 153 | 91.606 | 0.534 | 0.941 | 0.000 |
| 09 | existing_semantic_output | 4 | 6.460 | 0.267 | 0.267 | 0.000 |
| 09 | nonoverlap_plus_singleton | 0 | 0.000 | — | — | 0.000 |
| 09 | scene_aware_plus_singleton | 0 | 0.000 | — | — | 0.000 |
| 09 | simplified_cut_mask_plus_singleton | 0 | 0.000 | — | — | 0.000 |
| 09 | simplified_scene_reset_plus_singleton | 0 | 0.000 | — | — | 0.000 |
| 12 | existing_semantic_output | 15 | 100.000 | 0.400 | 2.504 | 1.865 |
| 12 | nonoverlap_plus_singleton | 7 | 100.000 | 0.267 | 5.100 | 0.000 |
| 12 | scene_aware_plus_singleton | 7 | 100.000 | 0.267 | 5.100 | 0.000 |
| 12 | simplified_cut_mask_plus_singleton | 15 | 100.000 | 0.267 | 2.380 | 0.000 |
| 12 | simplified_scene_reset_plus_singleton | 15 | 100.000 | 0.267 | 2.380 | 0.000 |

## Video 09 reviewed cases

| Audit ID | Review | Production cut on support | existing_semantic_output | nonoverlap_plus_singleton | scene_aware_plus_singleton | simplified_cut_mask_plus_singleton | simplified_scene_reset_plus_singleton |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M001 | no_meaningful_motion | True | yes | no | no | no | no |
| M029 | no_meaningful_motion | True | yes | no | no | no | no |
| M037 | no_meaningful_motion | True | yes | no | no | no | no |
| M049 | no_meaningful_motion | True | yes | no | no | no | no |

## Interpretation and recommendation

The current semantic pan/zoom/shake/general labels failed Stage 4.1's exact-class review; scene reset removed edit artifacts but did not rescue those meanings. The neutral contract should be judged on motion presence and spatial locality only. Cut-associated cases are identified by the production detector, not repaired truth. The selected audit and its single-review provenance limit confidence in precision/recall estimates.

The simplified variant retains 36/38 visually valid cases, but also retains 7/15 reviewed no-motion cases. Its local label is correct in 7/8 emitted reviewed local cases and finds only 7/32 visually local cases. Local is therefore a sparse positive signal, not a complete subject-motion detector. The two simplified variants have identical event intervals and labels across all 11 videos; the cut mask, rather than direction reset, determines this coarse contract in the pilot.

**Recommendation: B — use the simplified low-level contract as the V9 research direction.** Keep motion out of semantic downstream reasoning until independent review confirms meaningful presence and local specificity. If it fails that review, choose C and omit motion. A is unsupported by the reviewed class results. No production integration is authorized or made here.
