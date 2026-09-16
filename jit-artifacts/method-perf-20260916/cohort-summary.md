# Fixed pyperformance cohort

Completed paired workloads: 24/24. Lower runtime ratios are better.

| Workload | Main (ms) | Before/main | Candidate/main | Candidate/before | Candidate/main block range |
|---|---:|---:|---:|---:|---:|
| chaos | 33.741 | 1.0341 | 1.0570 | 1.0222 | 0.9841–1.1353 |
| comprehensions | 0.010 | 0.9581 | 0.9606 | 1.0027 | 0.9547–0.9666 |
| crypto_pyaes | 46.809 | 0.9728 | 0.9739 | 1.0012 | 0.9464–1.0023 |
| deltablue | 1.695 | 0.9437 | 0.9484 | 1.0050 | 0.9389–0.9581 |
| docutils | 1710.740 | 0.9990 | 0.9979 | 0.9989 | 0.9932–1.0027 |
| fannkuch | 211.434 | 1.0237 | 1.0219 | 0.9982 | 1.0211–1.0227 |
| float | 37.863 | 1.0098 | 1.0172 | 1.0074 | 1.0159–1.0185 |
| go | 63.476 | 1.3422 | 1.1240 | 0.8375 | 1.1160–1.1321 |
| hexiom | 3.437 | 1.0047 | 1.0063 | 1.0016 | 1.0034–1.0092 |
| html5lib | 37.219 | 0.9257 | 0.9311 | 1.0058 | 0.9153–0.9471 |
| json_dumps | 6.064 | 1.0055 | 1.0036 | 0.9981 | 0.9976–1.0096 |
| json_loads | 0.015 | 0.9881 | 0.9971 | 1.0091 | 0.9886–1.0057 |
| meteor_contest | 71.813 | 1.0055 | 1.0074 | 1.0018 | 1.0043–1.0105 |
| nbody | 40.826 | 0.9677 | 0.9708 | 1.0032 | 0.9650–0.9766 |
| nqueens | 49.017 | 1.0098 | 1.0200 | 1.0101 | 1.0103–1.0297 |
| pidigits | 135.115 | 1.0023 | 1.0010 | 0.9988 | 0.9968–1.0052 |
| raytrace | 155.716 | 1.0087 | 1.0354 | 1.0264 | 1.0220–1.0490 |
| regex_dna | 118.927 | 0.9953 | 0.9499 | 0.9544 | 0.9451–0.9548 |
| richards | 12.190 | 1.0270 | 1.0286 | 1.0016 | 1.0275–1.0298 |
| richards_super | 13.585 | 1.0442 | 1.0328 | 0.9891 | 1.0304–1.0353 |
| spectral_norm | 42.009 | 0.9876 | 0.9887 | 1.0011 | 0.9878–0.9895 |
| telco | 85.818 | 1.0637 | 1.0449 | 0.9823 | 1.0347–1.0552 |
| tomli_loads | 1059.317 | 0.9585 | 0.9608 | 1.0024 | 0.9522–0.9696 |
| networkx_connected_components | 309.981 | 1.0027 | 1.1297 | 1.1266 | 0.9910–1.2877 |

Geometric means: {'before/main': 1.0092352847960788, 'candidate/main': 1.0076064590114187, 'candidate/before': 0.998386079233259}

Two independent processes per binary/workload, five measured values per process after three warmups. The range describes two paired process ratios; it is not a confidence interval. Pilot calibration results are excluded from the comparison. Each workload has equal geometric-mean weight.
