# Q8 cold-window model screen

| CPU pacing | Model | 12-task cycles | Per-task cycles | Tasks/s |
|---|---|---:|---:|---:|
| response_relative | M0 | 850644 | 70887 | 2116.044 |
| response_relative | SERIAL64 | 728640 | 60720 | 2470.356 |
| response_relative | Q8 | 614976 | 51248 | 2926.943 |
| fixed_cpu | M0 | 850644 | 70887 | 2116.044 |
| fixed_cpu | SERIAL64 | 838368 | 69864 | 2147.029 |
| fixed_cpu | Q8 | 837864 | 69822 | 2148.320 |

The original R4+F2 observer matched the model cycle by cycle on the compared boundary signals.
The new firmware uses the same driver and changes the row-group constant from three to four.
The response-relative model maps measured MMIO gaps by corresponding control-flow edges. The fixed pace anchors each request to the old descriptor covering the same row.
Only Q8 passed the selection rule. All normal, mixed-paused and single-word Verilator cases passed. The original mixed bench did not cover a cross-generation pair because word 255 was forced to use a single write. The revised stimulus covers that pair and the RTL is unchanged.
