# V9 Stage 3 scene threshold sweep

Provisional Gemini + human-checked calibration references for 11 pilot videos. These are not production ground truth; no population accuracy is inferred.

Detector: `scenedetect.detectors.ContentDetector`, PySceneDetect `0.7.1`. Threshold 27 is the unchanged production baseline. All other settings use the recorded defaults in JSON. Each video was normalised once with the production preprocessing function; only scene detection was run.

## Interpretation

Threshold 36 leads at ±0.5 s F1 (0.503 versus 0.500 at 27), a small 0.003 gain. It yields 51 fewer predicted cuts and 12 fewer matched boundaries. The sweep supports some sensitivity concerns, but does not establish a material overall gain from changing only the threshold.

Videos 04 and 07 still have many false positives at the leading threshold, and video 09 still has false detections despite zero reference boundaries. Video 03 remains strong. Higher thresholds reduce some false positives while also losing true matches; no production threshold is selected here.

## Aggregate (ranked by ±0.5 s F1)

| Threshold | TP | FP | FN | Precision | Recall | F1 | Mean matched error (s) | Predicted cuts |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 36 | 114 | 154 | 71 | 0.425 | 0.616 | 0.503 | 0.246 | 268 |
| 30 | 124 | 185 | 61 | 0.401 | 0.670 | 0.502 | 0.237 | 309 |
| 27 (baseline) | 126 | 193 | 59 | 0.395 | 0.681 | 0.500 | 0.242 | 319 |
| 40 | 105 | 134 | 80 | 0.439 | 0.568 | 0.495 | 0.253 | 239 |
| 33 | 117 | 171 | 68 | 0.406 | 0.632 | 0.495 | 0.241 | 288 |
| 24 | 126 | 200 | 59 | 0.387 | 0.681 | 0.493 | 0.240 | 326 |
| 20 | 128 | 209 | 57 | 0.380 | 0.692 | 0.490 | 0.238 | 337 |
| 45 | 93 | 120 | 92 | 0.437 | 0.503 | 0.467 | 0.245 | 213 |

## Aggregate at ±0.1 s

| Threshold | TP | FP | FN | Precision | Recall | F1 | Mean matched error (s) | Predicted cuts |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 36 | 21 | 247 | 164 | 0.078 | 0.114 | 0.093 | 0.048 | 268 |
| 30 | 25 | 284 | 160 | 0.081 | 0.135 | 0.101 | 0.049 | 309 |
| 27 | 25 | 294 | 160 | 0.078 | 0.135 | 0.099 | 0.050 | 319 |
| 40 | 19 | 220 | 166 | 0.079 | 0.103 | 0.090 | 0.051 | 239 |
| 33 | 23 | 265 | 162 | 0.080 | 0.124 | 0.097 | 0.046 | 288 |
| 24 | 24 | 302 | 161 | 0.074 | 0.130 | 0.094 | 0.051 | 326 |
| 20 | 25 | 312 | 160 | 0.074 | 0.135 | 0.096 | 0.050 | 337 |
| 45 | 17 | 196 | 168 | 0.080 | 0.092 | 0.085 | 0.048 | 213 |

## Aggregate at ±0.25 s

| Threshold | TP | FP | FN | Precision | Recall | F1 | Mean matched error (s) | Predicted cuts |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 36 | 62 | 206 | 123 | 0.231 | 0.335 | 0.274 | 0.133 | 268 |
| 30 | 70 | 239 | 115 | 0.227 | 0.378 | 0.283 | 0.131 | 309 |
| 27 | 70 | 249 | 115 | 0.219 | 0.378 | 0.278 | 0.131 | 319 |
| 40 | 54 | 185 | 131 | 0.226 | 0.292 | 0.255 | 0.132 | 239 |
| 33 | 65 | 223 | 120 | 0.226 | 0.351 | 0.275 | 0.131 | 288 |
| 24 | 72 | 254 | 113 | 0.221 | 0.389 | 0.282 | 0.133 | 326 |
| 20 | 76 | 261 | 109 | 0.226 | 0.411 | 0.291 | 0.135 | 337 |
| 45 | 51 | 162 | 134 | 0.239 | 0.276 | 0.256 | 0.134 | 213 |

## Per-video at ±0.5 s

Video 09 has zero reference boundaries. Its recall and F1 are undefined; predicted cuts remain visible as false positives.

| Video | Reference cuts | 20: P / R / F1 / cuts | 24: P / R / F1 / cuts | 27: P / R / F1 / cuts | 30: P / R / F1 / cuts | 33: P / R / F1 / cuts | 36: P / R / F1 / cuts | 40: P / R / F1 / cuts | 45: P / R / F1 / cuts |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| **01** | 7 | 0.375 / 0.429 / 0.400 / 8 | 0.375 / 0.429 / 0.400 / 8 | 0.375 / 0.429 / 0.400 / 8 | 0.375 / 0.429 / 0.400 / 8 | 0.375 / 0.429 / 0.400 / 8 | 0.429 / 0.429 / 0.429 / 7 | 0.500 / 0.429 / 0.462 / 6 | 0.500 / 0.429 / 0.462 / 6 |
| **03** | 26 | 0.727 / 0.923 / 0.814 / 33 | 0.727 / 0.923 / 0.814 / 33 | 0.727 / 0.923 / 0.814 / 33 | 0.727 / 0.923 / 0.814 / 33 | 0.727 / 0.923 / 0.814 / 33 | 0.774 / 0.923 / 0.842 / 31 | 0.767 / 0.885 / 0.821 / 30 | 0.759 / 0.846 / 0.800 / 29 |
| **04** | 32 | 0.261 / 0.562 / 0.356 / 69 | 0.288 / 0.594 / 0.388 / 66 | 0.288 / 0.594 / 0.388 / 66 | 0.297 / 0.594 / 0.396 / 64 | 0.262 / 0.500 / 0.344 / 61 | 0.276 / 0.500 / 0.356 / 58 | 0.302 / 0.500 / 0.376 / 53 | 0.300 / 0.469 / 0.366 / 50 |
| **05** | 25 | 0.378 / 0.560 / 0.452 / 37 | 0.395 / 0.600 / 0.476 / 38 | 0.395 / 0.600 / 0.476 / 38 | 0.385 / 0.600 / 0.469 / 39 | 0.410 / 0.640 / 0.500 / 39 | 0.395 / 0.600 / 0.476 / 38 | 0.429 / 0.600 / 0.500 / 35 | 0.455 / 0.600 / 0.517 / 33 |
| **06** | 13 | 0.471 / 0.615 / 0.533 / 17 | 0.571 / 0.615 / 0.593 / 14 | 0.571 / 0.615 / 0.593 / 14 | 0.571 / 0.615 / 0.593 / 14 | 0.571 / 0.615 / 0.593 / 14 | 0.667 / 0.615 / 0.640 / 12 | 0.500 / 0.462 / 0.480 / 12 | 0.667 / 0.462 / 0.545 / 9 |
| **07** | 37 | 0.321 / 0.703 / 0.441 / 81 | 0.295 / 0.622 / 0.400 / 78 | 0.315 / 0.622 / 0.418 / 73 | 0.324 / 0.622 / 0.426 / 71 | 0.329 / 0.622 / 0.430 / 70 | 0.333 / 0.595 / 0.427 / 66 | 0.339 / 0.568 / 0.424 / 62 | 0.321 / 0.459 / 0.378 / 53 |
| **08** | 14 | 0.423 / 0.786 / 0.550 / 26 | 0.400 / 0.714 / 0.513 / 25 | 0.417 / 0.714 / 0.526 / 24 | 0.455 / 0.714 / 0.556 / 22 | 0.444 / 0.571 / 0.500 / 18 | 0.438 / 0.500 / 0.467 / 16 | 0.538 / 0.500 / 0.519 / 13 | 0.455 / 0.357 / 0.400 / 11 |
| **09** | 0 | 0.000 / — / — / 5 | 0.000 / — / — / 5 | 0.000 / — / — / 5 | 0.000 / — / — / 4 | 0.000 / — / — / 4 | 0.000 / — / — / 4 | 0.000 / — / — / 4 | 0.000 / — / — / 4 |
| **10** | 12 | 0.423 / 0.917 / 0.579 / 26 | 0.423 / 0.917 / 0.579 / 26 | 0.423 / 0.917 / 0.579 / 26 | 0.435 / 0.833 / 0.571 / 23 | 0.455 / 0.833 / 0.588 / 22 | 0.474 / 0.750 / 0.581 / 19 | 0.500 / 0.417 / 0.455 / 10 | 0.600 / 0.250 / 0.353 / 5 |
| **11** | 19 | 0.371 / 0.684 / 0.481 / 35 | 0.394 / 0.684 / 0.500 / 33 | 0.406 / 0.684 / 0.510 / 32 | 0.387 / 0.632 / 0.480 / 31 | 0.474 / 0.474 / 0.474 / 19 | 0.588 / 0.526 / 0.556 / 17 | 0.643 / 0.474 / 0.545 / 14 | 0.538 / 0.368 / 0.438 / 13 |
| **12** | 0 | — / — / — / 0 | — / — / — / 0 | — / — / — / 0 | — / — / — / 0 | — / — / — / 0 | — / — / — / 0 | — / — / — / 0 | — / — / — / 0 |

The JSON contains every video's scores at ±0.1, ±0.25, and ±0.5 s, including unmatched timestamps. Ranking is descriptive; precision, recall, and videos 03, 04, 07, and 09 should guide any later decision.

## Reproduce

Run `python -m intelligence.evaluation.stage3_scene --manifest MANIFEST --truth-dir PROVISIONAL_REVIEWED --baseline-dir PILOT_RESULTS --json OUTPUT.json --markdown OUTPUT.md` from `backend` using an environment with PySceneDetect and FFmpeg. The private manifest, media, reference files, and baseline analysis files are inputs; the command runs normalisation and scene detection only.
