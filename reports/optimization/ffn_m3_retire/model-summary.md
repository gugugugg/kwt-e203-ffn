# M3 result retirement model

One native M3 case calibrated the causal model at the published 75,601-cycle boundary. The same 12 cold inputs were then evaluated under both CPU schedules.

| CPU schedule | Model | Total cycles | Cycles per task | Tasks/s | Third-row stalls per task | Adjacent paired reads | Write handoffs | Direct FIFO halfwords |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| response_relative | M0 | 907212 | 75601 | 1984.10 | 6304 | 0 | 0 | 0 |
| response_relative | R4 | 854604 | 71217 | 2106.24 | 2176 | 7871 | 7937 | 0 |
| response_relative | R4+F2 | 850644 | 70887 | 2116.04 | 1856 | 7871 | 7904 | 4852 |
| fixed_cpu | M0 | 907212 | 75601 | 1984.10 | 6304 | 0 | 0 | 0 |
| fixed_cpu | R4 | 902472 | 75206 | 1994.52 | 2176 | 7871 | 7937 | 0 |
| fixed_cpu | R4+F2 | 902580 | 75215 | 1994.28 | 1856 | 7871 | 7904 | 3300 |

R4+F2 wins under the response-relative rule, with 4,714 fewer cycles per task. The fixed CPU schedule yields 386 cycles saved per task and ranks R4 ahead by nine cycles. Fixed pacing preserves the observed earliest issue time, so a faster downstream response cannot advance a later CPU request beyond that time.

All cases check the complete cold window, 11,936 payload words plus the original guards and controls, 68 descriptors, 11,936 DMA reads, 12,672 physical output writes and 25,344 golden values in retirement order. The model generates its own queue and port handshakes. The observed workload supplies CPU issue gaps and the initial host traffic.

The only candidate RTL delta is the private result queue. The actual, mixed-paused and single-word regressions passed all 36 tasks. M3 remains the published version.
