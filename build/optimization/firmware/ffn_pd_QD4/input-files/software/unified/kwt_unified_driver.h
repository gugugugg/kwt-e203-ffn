#ifndef KWT_UNIFIED_DRIVER_H
#define KWT_UNIFIED_DRIVER_H
#include <stdint.h>
#include <stddef.h>
enum { KWU_ENCODER=0, KWU_LINEAR=1, KWU_OK=0, KWU_HW_ERROR=-1 };
typedef struct { uintptr_t base; } kwu_device;
/* Packets contain aligned little-endian uint32 words, two int16 codes per word. */
typedef int (*kwu_stage_layer)(void *context,unsigned layer,
                              const uint32_t **parameters,const uint32_t **metadata);
int kwu_run_encoder(const kwu_device *device,const uint32_t input[3168],
                    const uint32_t exp_table[4097],const uint32_t gelu_table[4097],
                    kwu_stage_layer stage,void *context,int16_t output[6336]);
int kwu_run_linear(const kwu_device *device,const uint32_t input[3168],
                   kwu_stage_layer stage,void *context,int16_t output[25344]);
#endif
