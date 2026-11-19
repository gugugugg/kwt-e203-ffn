# R3O stream model screening

M0 reproduces the published 87,626-cycle cold window. The legacy last_emit marker records the last row-0 FIFO push at 87,099. The same native observation records the last successful three-row quantization at 87,101, last physical SRAM commit at 87,625, and ACK at 87,627.

The same causal hardware model with the adapted SR CPU cadence takes 62 extra cycles. It also observes 62 extra quantization stalls. Both first MAC and input-wait counts match.

| Model | 12-task response-relative cycles | Tasks/s | 12-task fixed-CPU cycles |
|---|---:|---:|---:|
| M0 | 1,051,512 | 1711.820692 | 1,051,512 |
| M1 | 947,064 | 1900.610730 | 1,051,512 |
| M2 | 947,052 | 1900.634812 | 1,051,512 |
| M3 | 907,212 | 1984.100739 | 1,051,512 |

M3 alone is selected. In the response-relative model it takes 75,601 cycles per task, 601 cycles above the 2,000 tasks/s target. The fixed-CPU sensitivity run retains the original issue deadlines and final commit time.

All 96 model cases checked committed output values and addresses, 25,344 ordered retirements, 11,936 host payload words plus ten setup/control writes, 11,936 DMA reads, 12,672 writes, and 68 descriptors.
