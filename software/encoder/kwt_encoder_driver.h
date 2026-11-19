#ifndef KWT_ENCODER_DRIVER_H
#define KWT_ENCODER_DRIVER_H
#include <stdint.h>
#include <stddef.h>
enum { KWE_OK=0,KWE_BAD_ARGUMENT=-1,KWE_HW_ERROR=-2,KWE_TIMEOUT=-3 };
typedef struct { uintptr_t base; uint32_t poll_limit; } kwe_device;
/* The loader stages one layer into the platform shared SRAM. No numerical math. */
typedef int (*kwe_stage_layer)(void *context,unsigned layer,
                              const uint16_t **parameters,const uint16_t **config);
int kwe_run(const kwe_device *device,const int16_t input[6336],
            const uint16_t exp_words[8194],const uint16_t gelu_words[8194],
            kwe_stage_layer stage_layer,void *context,int16_t output[6336]);
#endif
