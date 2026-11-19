# P2 startup and group-boundary selection

P2 case 1 was observed once with the frozen public SoC, frozen firmware and a passive testbench observer. The archived observation matches first MAC 1662, last quantization 34268, last physical write 34535, ACK 34536 and 34536 cold cycles. The model compared physical SRAM accepts, writes, bank-mapped addresses, dual accepts, DMA occupancy and CPU response timing against that trace.

The earlier model used instruction gaps inferred from W4Z+FT. Its first four descriptor launch cycles were 752, 1047, 1216 and 1525, versus P2's actual 755, 1050, 1214 and 1529. The first MAC and both final endpoints moved by four cycles with P2's observed handshake program. The corrected model advances the bus and queue independently of the recorded ready signals.

| Model | Response-relative cycles, 12 tasks | Fixed CPU cycles, 12 tasks |
|---|---:|---:|
| M0 | 414432 | 414432 |
| S | 408288 | 415980 |
| G | 412056 | 412056 |
| S+G | 405912 | 413604 |

Each case verifies 11680 host payload words, five guards and five control writes, 11680 DMA reads, 12672 physical result writes, 52 descriptors and 25344 bit-exact ordered results. The response-relative model makes S+G the sole hardware candidate. It predicts 33826 cycles and 4434.46 tasks/s, with all 22 eligible boundaries joining. The fixed-CPU floor retains P2's issue time slots and demonstrates sensitivity to the changed CPU schedule. The formal cold-task performance comes from the candidate's own E203 CPU12.
