/* Compilation probe only: no board address map or accelerator driver assumed. */
#include <stdint.h>

int32_t environment_dot64(const int16_t *lhs, const int16_t *rhs) {
    int32_t total = 0;
    for (unsigned i = 0; i < 64; ++i) total += (int32_t)lhs[i] * rhs[i];
    return total;
}
