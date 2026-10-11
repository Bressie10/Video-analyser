# V9 Stage 4: offline motion event stabilization

Production `_classify_optical_flow()` and `detect_motion_events()` are unchanged. The 11 source videos are 01 and 03–12; 02 is not in the pilot. The experiment repeats production normalization, sampling, Farnebäck flow and classification. Every reconstructed baseline event was compared to its stored pilot event.

No independent motion ground truth is available. Event count, duration, coverage and overlap measure output structure, not motion accuracy.

## Method

Each raw record contains comparison timestamp, predicted type (null means no motion), and confidence. Corrected intervals are half-open sample cells. The final class run extends to video duration, as in production. Baseline is the current event builder. Nonoverlap clips the start of each baseline event to the previous end. Merge identical builds maximal runs from raw cells; production already merges consecutive identical labels, so event counts may be unchanged. Singleton suppression replaces A-B-A with A-A-A, scanning left to right and skipping adjacent conflicting replacements. Confidence remains the original sample confidence. Minimum durations apply after singleton suppression and discard short runs as gaps. Unknown-as-gap also follows singleton suppression; the combined 0.5 s variant applies both filters.

Coverage is the union of emitted event intervals / total video duration. Overlap is time covered by at least two events. All per-video and aggregate values are in the JSON.

## Aggregate results

| Configuration | Events | Events/min | Median s | Mean s | Coverage % | Overlap s | Counts by type |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| baseline | 1351 | 121.104 | 0.267 | 0.589 | 93.692 | 169.244 | camera_pan 151, camera_zoom 107, camera_shake 76, local_motion 280, general_motion 460, unknown 277 |
| nonoverlap_only | 1351 | 121.104 | 0.250 | 0.464 | 93.692 | 0.000 | camera_pan 151, camera_zoom 107, camera_shake 76, local_motion 280, general_motion 460, unknown 277 |
| merge_identical | 1351 | 121.104 | 0.134 | 0.459 | 92.743 | 0.000 | camera_pan 151, camera_zoom 107, camera_shake 76, local_motion 280, general_motion 460, unknown 277 |
| short_run_suppression | 735 | 65.886 | 0.375 | 0.845 | 92.741 | 0.000 | camera_pan 104, camera_zoom 62, camera_shake 45, local_motion 129, general_motion 250, unknown 145 |
| min_0.25 | 516 | 46.254 | 0.625 | 1.147 | 88.459 | 0.000 | camera_pan 79, camera_zoom 49, camera_shake 15, local_motion 118, general_motion 173, unknown 82 |
| min_0.5 | 305 | 27.340 | 1.067 | 1.726 | 78.669 | 0.000 | camera_pan 41, camera_zoom 31, camera_shake 0, local_motion 86, general_motion 102, unknown 45 |
| min_0.75 | 221 | 19.810 | 1.333 | 2.160 | 71.310 | 0.000 | camera_pan 27, camera_zoom 25, camera_shake 0, local_motion 75, general_motion 65, unknown 29 |
| unknown_as_gap | 590 | 52.888 | 0.400 | 0.939 | 82.732 | 0.000 | camera_pan 104, camera_zoom 62, camera_shake 45, local_motion 129, general_motion 250, unknown 0 |
| unknown_gap_min_0.5 | 260 | 23.306 | 1.067 | 1.846 | 71.716 | 0.000 | camera_pan 41, camera_zoom 31, camera_shake 0, local_motion 86, general_motion 102, unknown 0 |

The baseline counts match the stored pilot exactly: 1,351 overall, 394 for 04 and 350 for 07. Its overlap is 169.244 s. Clipping intervals alone removes overlap without changing event count. Rebuilding maximal raw-class runs also removes the baseline's extra coverage of the first no-motion sample after a run. The 0.5 s filter removes all camera_shake events in this pilot; this is a loss of output, not evidence that those samples were incorrect.

## Focus videos

| Video | Baseline | Singleton suppression | Minimum 0.5 s | Unknown as gap |
| --- | ---: | ---: | ---: | ---: |
| **04** | 394 | 228 | 94 | 180 |
| **07** | 350 | 219 | 79 | 182 |
| **09** | 4 | 0 | 0 | 0 |
| **12** | 15 | 7 | 3 | 7 |

Video 09 has four baseline events and none after singleton suppression. The per-video table below shows duration, coverage, overlap and type counts for every configuration, including 04, 07, 09 and 12.


## Per-video results

Each row reports all requested metrics. Type counts use pan/zoom/shake/local/general/unknown order.

| Video | Configuration | Events | Events/min | Median s | Mean s | Coverage % | Overlap s | Type counts |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| **01** | baseline | 56 | 117.073 | 0.267 | 0.644 | 100.000 | 7.337 | 1/1/2/11/24/17 |
| **01** | nonoverlap_only | 56 | 117.073 | 0.200 | 0.512 | 100.000 | 0.000 | 1/1/2/11/24/17 |
| **01** | merge_identical | 56 | 117.073 | 0.134 | 0.512 | 100.000 | 0.000 | 1/1/2/11/24/17 |
| **01** | short_run_suppression | 26 | 54.355 | 0.800 | 1.104 | 100.000 | 0.000 | 1/1/1/5/10/8 |
| **01** | min_0.25 | 20 | 41.812 | 0.867 | 1.395 | 97.213 | 0.000 | 1/0/0/5/10/4 |
| **01** | min_0.5 | 16 | 33.449 | 1.416 | 1.644 | 91.638 | 0.000 | 1/0/0/5/9/1 |
| **01** | min_0.75 | 14 | 29.268 | 1.466 | 1.793 | 87.453 | 0.000 | 1/0/0/4/8/1 |
| **01** | unknown_as_gap | 18 | 37.631 | 1.084 | 1.446 | 90.704 | 0.000 | 1/1/1/5/10/0 |
| **01** | unknown_gap_min_0.5 | 15 | 31.359 | 1.466 | 1.691 | 88.383 | 0.000 | 1/0/0/5/9/0 |
| **03** | baseline | 102 | 112.113 | 0.267 | 0.636 | 96.333 | 12.276 | 4/3/3/45/35/12 |
| **03** | nonoverlap_only | 102 | 112.113 | 0.266 | 0.516 | 96.333 | 0.000 | 4/3/3/45/35/12 |
| **03** | merge_identical | 102 | 112.113 | 0.134 | 0.504 | 94.134 | 0.000 | 4/3/3/45/35/12 |
| **03** | short_run_suppression | 37 | 40.668 | 0.400 | 1.385 | 93.887 | 0.000 | 2/3/1/14/12/5 |
| **03** | min_0.25 | 25 | 27.479 | 0.801 | 1.986 | 90.954 | 0.000 | 2/1/0/14/7/1 |
| **03** | min_0.5 | 16 | 17.586 | 1.935 | 2.920 | 85.576 | 0.000 | 1/0/0/11/4/0 |
| **03** | min_0.75 | 13 | 14.289 | 2.269 | 3.460 | 82.397 | 0.000 | 1/0/0/10/2/0 |
| **03** | unknown_as_gap | 32 | 35.173 | 0.467 | 1.572 | 92.176 | 0.000 | 2/3/1/14/12/0 |
| **03** | unknown_gap_min_0.5 | 16 | 17.586 | 1.935 | 2.920 | 85.576 | 0.000 | 1/0/0/11/4/0 |
| **04** | baseline | 394 | 170.686 | 0.375 | 0.476 | 100.000 | 49.125 | 76/67/24/12/132/83 |
| **04** | nonoverlap_only | 394 | 170.686 | 0.250 | 0.352 | 100.000 | 0.000 | 76/67/24/12/132/83 |
| **04** | merge_identical | 394 | 170.686 | 0.250 | 0.352 | 100.000 | 0.000 | 76/67/24/12/132/83 |
| **04** | short_run_suppression | 228 | 98.773 | 0.375 | 0.607 | 100.000 | 0.000 | 46/34/13/6/81/48 |
| **04** | min_0.25 | 173 | 74.946 | 0.500 | 0.761 | 95.036 | 0.000 | 39/28/6/4/60/36 |
| **04** | min_0.5 | 94 | 40.722 | 0.875 | 1.148 | 77.888 | 0.000 | 18/20/0/3/32/21 |
| **04** | min_0.75 | 65 | 28.159 | 1.125 | 1.410 | 66.155 | 0.000 | 10/16/0/2/23/14 |
| **04** | unknown_as_gap | 180 | 77.978 | 0.375 | 0.622 | 80.776 | 0.000 | 46/34/13/6/81/0 |
| **04** | unknown_gap_min_0.5 | 73 | 31.625 | 0.875 | 1.202 | 63.357 | 0.000 | 18/20/0/3/32/0 |
| **05** | baseline | 147 | 175.173 | 0.267 | 0.443 | 91.717 | 18.952 | 11/4/11/27/50/44 |
| **05** | nonoverlap_only | 147 | 175.173 | 0.134 | 0.314 | 91.717 | 0.000 | 11/4/11/27/50/44 |
| **05** | merge_identical | 147 | 175.173 | 0.134 | 0.310 | 90.393 | 0.000 | 11/4/11/27/50/44 |
| **05** | short_run_suppression | 77 | 91.757 | 0.267 | 0.588 | 89.862 | 0.000 | 6/1/7/18/24/21 |
| **05** | min_0.25 | 49 | 58.391 | 0.800 | 0.847 | 82.436 | 0.000 | 1/0/1/16/18/13 |
| **05** | min_0.5 | 35 | 41.708 | 0.934 | 1.068 | 74.220 | 0.000 | 0/0/0/11/13/11 |
| **05** | min_0.75 | 25 | 29.791 | 1.068 | 1.260 | 62.556 | 0.000 | 0/0/0/8/8/9 |
| **05** | unknown_as_gap | 56 | 66.732 | 0.267 | 0.553 | 61.497 | 0.000 | 6/1/7/18/24/0 |
| **05** | unknown_gap_min_0.5 | 24 | 28.600 | 0.867 | 1.029 | 49.034 | 0.000 | 0/0/0/11/13/0 |
| **06** | baseline | 50 | 60.281 | 0.400 | 0.861 | 75.016 | 5.730 | 9/10/2/9/16/4 |
| **06** | nonoverlap_only | 50 | 60.281 | 0.267 | 0.747 | 75.016 | 0.000 | 9/10/2/9/16/4 |
| **06** | merge_identical | 50 | 60.281 | 0.267 | 0.728 | 73.143 | 0.000 | 9/10/2/9/16/4 |
| **06** | short_run_suppression | 37 | 44.608 | 0.400 | 0.987 | 73.411 | 0.000 | 8/7/2/4/13/3 |
| **06** | min_0.25 | 27 | 32.552 | 0.666 | 1.304 | 70.732 | 0.000 | 7/7/1/4/6/2 |
| **06** | min_0.5 | 16 | 19.290 | 0.867 | 1.983 | 63.764 | 0.000 | 5/3/0/4/3/1 |
| **06** | min_0.75 | 11 | 13.262 | 1.733 | 2.594 | 57.336 | 0.000 | 4/3/0/3/0/1 |
| **06** | unknown_as_gap | 34 | 40.991 | 0.400 | 0.980 | 66.979 | 0.000 | 8/7/2/4/13/0 |
| **06** | unknown_gap_min_0.5 | 15 | 18.084 | 0.800 | 1.938 | 58.405 | 0.000 | 5/3/0/4/3/0 |
| **07** | baseline | 350 | 133.616 | 0.267 | 0.573 | 98.898 | 44.942 | 46/20/30/78/117/59 |
| **07** | nonoverlap_only | 350 | 133.616 | 0.134 | 0.444 | 98.898 | 0.000 | 46/20/30/78/117/59 |
| **07** | merge_identical | 350 | 133.616 | 0.134 | 0.440 | 97.880 | 0.000 | 46/20/30/78/117/59 |
| **07** | short_run_suppression | 219 | 83.606 | 0.267 | 0.704 | 98.135 | 0.000 | 37/14/18/41/72/37 |
| **07** | min_0.25 | 142 | 54.210 | 0.534 | 1.014 | 91.600 | 0.000 | 27/12/5/35/42/21 |
| **07** | min_0.5 | 79 | 30.159 | 1.067 | 1.568 | 78.791 | 0.000 | 14/7/0/27/22/9 |
| **07** | min_0.75 | 56 | 21.379 | 1.333 | 1.961 | 69.883 | 0.000 | 10/5/0/23/14/4 |
| **07** | unknown_as_gap | 182 | 69.480 | 0.400 | 0.768 | 88.886 | 0.000 | 37/14/18/41/72/0 |
| **07** | unknown_gap_min_0.5 | 70 | 26.723 | 1.067 | 1.643 | 73.192 | 0.000 | 14/7/0/27/22/0 |
| **08** | baseline | 79 | 172.573 | 0.267 | 0.468 | 97.089 | 10.267 | 1/0/3/21/29/25 |
| **08** | nonoverlap_only | 79 | 172.573 | 0.134 | 0.338 | 97.089 | 0.000 | 1/0/3/21/29/25 |
| **08** | merge_identical | 79 | 172.573 | 0.134 | 0.334 | 96.117 | 0.000 | 1/0/3/21/29/25 |
| **08** | short_run_suppression | 38 | 83.010 | 0.400 | 0.698 | 96.601 | 0.000 | 1/0/2/12/13/10 |
| **08** | min_0.25 | 28 | 61.165 | 0.666 | 0.900 | 91.748 | 0.000 | 0/0/2/11/11/4 |
| **08** | min_0.5 | 18 | 39.320 | 0.934 | 1.222 | 80.090 | 0.000 | 0/0/0/6/10/2 |
| **08** | min_0.75 | 12 | 26.214 | 1.133 | 1.533 | 66.994 | 0.000 | 0/0/0/6/6/0 |
| **08** | unknown_as_gap | 28 | 61.165 | 0.533 | 0.843 | 85.930 | 0.000 | 1/0/2/12/13/0 |
| **08** | unknown_gap_min_0.5 | 16 | 34.951 | 1.067 | 1.292 | 75.240 | 0.000 | 0/0/0/6/10/0 |
| **09** | baseline | 4 | 14.516 | 0.267 | 0.267 | 6.460 | 0.000 | 0/0/0/0/4/0 |
| **09** | nonoverlap_only | 4 | 14.516 | 0.267 | 0.267 | 6.460 | 0.000 | 0/0/0/0/4/0 |
| **09** | merge_identical | 4 | 14.516 | 0.133 | 0.133 | 3.230 | 0.000 | 0/0/0/0/4/0 |
| **09** | short_run_suppression | 0 | 0.000 | — | — | 0.000 | 0.000 | 0/0/0/0/0/0 |
| **09** | min_0.25 | 0 | 0.000 | — | — | 0.000 | 0.000 | 0/0/0/0/0/0 |
| **09** | min_0.5 | 0 | 0.000 | — | — | 0.000 | 0.000 | 0/0/0/0/0/0 |
| **09** | min_0.75 | 0 | 0.000 | — | — | 0.000 | 0.000 | 0/0/0/0/0/0 |
| **09** | unknown_as_gap | 0 | 0.000 | — | — | 0.000 | 0.000 | 0/0/0/0/0/0 |
| **09** | unknown_gap_min_0.5 | 0 | 0.000 | — | — | 0.000 | 0.000 | 0/0/0/0/0/0 |
| **10** | baseline | 77 | 149.676 | 0.267 | 0.518 | 97.192 | 9.866 | 0/0/0/34/19/24 |
| **10** | nonoverlap_only | 77 | 149.676 | 0.134 | 0.390 | 97.192 | 0.000 | 0/0/0/34/19/24 |
| **10** | merge_identical | 77 | 149.676 | 0.134 | 0.384 | 95.893 | 0.000 | 0/0/0/34/19/24 |
| **10** | short_run_suppression | 30 | 58.315 | 0.466 | 0.991 | 96.327 | 0.000 | 0/0/0/11/11/8 |
| **10** | min_0.25 | 20 | 38.877 | 0.867 | 1.420 | 92.009 | 0.000 | 0/0/0/11/9/0 |
| **10** | min_0.5 | 15 | 29.158 | 1.333 | 1.769 | 85.963 | 0.000 | 0/0/0/7/8/0 |
| **10** | min_0.75 | 11 | 21.382 | 1.600 | 2.194 | 78.188 | 0.000 | 0/0/0/7/4/0 |
| **10** | unknown_as_gap | 22 | 42.765 | 0.733 | 1.303 | 92.870 | 0.000 | 0/0/0/11/11/0 |
| **10** | unknown_gap_min_0.5 | 15 | 29.158 | 1.333 | 1.769 | 85.963 | 0.000 | 0/0/0/7/8/0 |
| **11** | baseline | 77 | 57.964 | 0.375 | 1.089 | 94.035 | 8.884 | 3/2/1/35/27/9 |
| **11** | nonoverlap_only | 77 | 57.964 | 0.250 | 0.973 | 94.035 | 0.000 | 3/2/1/35/27/9 |
| **11** | merge_identical | 77 | 57.964 | 0.250 | 0.964 | 93.092 | 0.000 | 3/2/1/35/27/9 |
| **11** | short_run_suppression | 36 | 27.100 | 0.250 | 2.065 | 93.249 | 0.000 | 3/2/1/14/11/5 |
| **11** | min_0.25 | 25 | 18.819 | 0.500 | 2.918 | 91.524 | 0.000 | 2/1/0/14/7/1 |
| **11** | min_0.5 | 13 | 9.786 | 3.129 | 5.352 | 87.287 | 0.000 | 2/1/0/9/1/0 |
| **11** | min_0.75 | 11 | 8.281 | 4.129 | 6.234 | 86.031 | 0.000 | 1/1/0/9/0/0 |
| **11** | unknown_as_gap | 31 | 23.336 | 0.375 | 2.373 | 92.308 | 0.000 | 3/2/1/14/11/0 |
| **11** | unknown_gap_min_0.5 | 13 | 9.786 | 3.129 | 5.352 | 87.287 | 0.000 | 2/1/0/9/1/0 |
| **12** | baseline | 15 | 25.210 | 0.400 | 2.504 | 100.000 | 1.865 | 0/0/0/8/7/0 |
| **12** | nonoverlap_only | 15 | 25.210 | 0.400 | 2.380 | 100.000 | 0.000 | 0/0/0/8/7/0 |
| **12** | merge_identical | 15 | 25.210 | 0.267 | 2.380 | 100.000 | 0.000 | 0/0/0/8/7/0 |
| **12** | short_run_suppression | 7 | 11.765 | 0.267 | 5.100 | 100.000 | 0.000 | 0/0/0/4/3/0 |
| **12** | min_0.25 | 7 | 11.765 | 0.267 | 5.100 | 100.000 | 0.000 | 0/0/0/4/3/0 |
| **12** | min_0.5 | 3 | 5.042 | 15.867 | 11.545 | 97.014 | 0.000 | 0/0/0/3/0/0 |
| **12** | min_0.75 | 3 | 5.042 | 15.867 | 11.545 | 97.014 | 0.000 | 0/0/0/3/0/0 |
| **12** | unknown_as_gap | 7 | 11.765 | 0.267 | 5.100 | 100.000 | 0.000 | 0/0/0/4/3/0 |
| **12** | unknown_gap_min_0.5 | 3 | 5.042 | 15.867 | 11.545 | 97.014 | 0.000 | 0/0/0/3/0/0 |

## Invariant and interpretation

Every corrected configuration has zero overlap between mutually exclusive class events; the raw baseline overlap is recorded above. No production configuration is selected. The experiment does not establish which motion labels are correct.
