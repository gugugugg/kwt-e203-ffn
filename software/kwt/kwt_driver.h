#ifndef KWT_DRIVER_H
#define KWT_DRIVER_H
#include <stddef.h>
#include <stdint.h>
/* The platform must supply the real MMIO base. There is no fabricated address. */
typedef struct { uintptr_t base; uint32_t poll_limit; } kwt_device;
enum { KWT_OK=0, KWT_TIMEOUT=-1, KWT_HW_ERROR=-2, KWT_BAD_ARGUMENT=-3 };
int kwt_ffn_run(const kwt_device *dev, const int16_t input[99*64],
                const int16_t kernel[64*256], const int64_t bias[256],
                int8_t shift, int16_t output[99*256]);
#endif
