#ifndef KWT_CHANNEL_DRIVER_H
#define KWT_CHANNEL_DRIVER_H
#include "kwt_driver.h"
int kwt_ffn_channel_run(const kwt_device *dev, const int16_t input[99*64],
                        const int16_t kernel[64*256], const int64_t bias[256],
                        const uint16_t shift_words[128], int8_t legacy_shift,
                        int16_t output[99*256]);
#endif
