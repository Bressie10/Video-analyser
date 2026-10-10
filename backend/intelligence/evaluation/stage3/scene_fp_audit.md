# V9 Stage 3.1 scene false-positive audit

Threshold 27; ±0.5 s one-to-one matching from the Stage 3 sweep. The reference remains provisional Gemini + human-checked calibration truth. This is a visual audit of 102 unmatched predictions in videos 04, 07 and 09, not an estimate of population detector accuracy.

Four decoded frames were inspected around each timestamp at approximately −0.25, −0.05, +0.05 and +0.25 s. Denser frame sequences were inspected for ambiguous events. A simple mean absolute pixel difference between the inner frames is recorded in JSON as context, not as a semantic classifier. Private frame evidence was kept outside Git because media rights are not independently verified.

## Observed categories

| Category | 04 | 07 | 09 | Total |
| --- | ---: | ---: | ---: | ---: |
| Likely editorial cut missing from reference | 40 | 43 | 0 | 83 |
| Likely editorial transition missing from reference | 1 | 2 | 0 | 3 |
| Animated graphic or split-screen layout | 0 | 5 | 0 | 5 |
| CGI or synthetic crowd change | 0 | 0 | 5 | 5 |
| Object or subject motion within a shot | 6 | 0 | 0 | 6 |

**Reference review:** 86 likely omitted boundaries; 11 possible boundary questions; 5 events without a clear editorial boundary.

## Timestamp examples

- **04 2.542 s:** roadside approach changes abruptly to a closer view; likely omitted cut. At 49.333 s, foam crosses the face within a continuous shot, a plausible detector false positive.
- **07 35.100 s:** workshop changes to helmet close-up; likely omitted cut. At 14.933 s, a blue text panel slides in; graphic boundary status needs adjudication.
- **09 2.200, 6.100, 10.200 and 14.067 s:** synthetic crowd and camera scale change abruptly; these could be edited CGI beat boundaries. At 15.000 s, frame-by-frame inspection showed only subtle crowd movement with no clear new composition.

## Suspected truth errors

Likely omitted editorial boundaries (reannotation candidates):

- **04 (41):** 2.542, 8.875, 10.375, 15.083, 18.417, 22.125, 23.583, 25.167, 26.458, 30.333, 32.542, 35.667, 37.333, 39.208, 40.958, 45.458, 47.417, 52.333, 55.000, 58.917, 61.667, 63.458, 64.917, 67.083, 70.292, 75.167, 77.583, 81.083, 83.167, 85.583, 88.542, 90.125, 91.875, 94.833, 99.250, 101.625, 105.125, 109.250, 131.792, 133.875, 137.250 s
- **07 (45):** 21.567, 28.433, 32.900, 35.100, 37.433, 39.300, 43.167, 44.667, 51.567, 54.300, 57.267, 58.800, 61.633, 63.267, 65.100, 67.500, 69.367, 72.067, 73.533, 74.933, 78.600, 81.067, 83.067, 84.967, 86.800, 90.333, 91.833, 93.533, 95.433, 96.667, 99.067, 100.600, 101.900, 103.533, 105.400, 106.800, 108.133, 109.533, 111.133, 113.300, 114.633, 115.767, 118.167, 119.400, 142.967 s

Possible boundary questions requiring adjudication:

- **04 (2):** 123.292, 127.042 s
- **07 (5):** 9.600, 14.933, 15.567, 132.800, 135.400 s
- **09 (4):** 2.200, 6.100, 10.200, 14.067 s

The 86 likely omissions mean the current provisional reference cannot reliably assign all unmatched detections to detector error. The CGI and graphic boundaries require an explicit annotation rule before being treated as either true cuts or false positives. No production detector change is proposed from this audit.

## Reproduce frame samples

From `backend`, run `python -m intelligence.evaluation.stage3_1_frames --manifest PRIVATE_MANIFEST --sweep intelligence/evaluation/stage3/scene_threshold_sweep.json --out PRIVATE_OUTPUT_DIR`. The command verifies source hashes, normalises each selected video once, and extracts the four sampled frames per unmatched prediction. It does not run scene detection or any other analysis signal. OpenCV seeks to approximate decoded frame times.
