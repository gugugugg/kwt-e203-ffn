"""Bit-exact FC1 arithmetic for the submitted 4x32 accelerator."""
import argparse

import numpy as np


def reference(inputs, weights, bias, shifts):
    inputs, weights, bias, shifts = (np.asarray(a) for a in (inputs, weights, bias, shifts))
    if (inputs.shape, weights.shape, bias.shape, shifts.shape) != ((99, 64), (64, 256), (256,), (256,)):
        raise ValueError("Expected inputs[99,64], weights[64,256], bias[256], shift[256]")
    for array, lo, hi in ((inputs, -32768, 32767), (weights, -32768, 32767),
                          (bias, -(1 << 31), (1 << 31) - 1), (shifts, -128, 127)):
        if array.dtype.kind not in "iu" or np.any(array < lo) or np.any(array > hi):
            raise ValueError("Invalid fixed-point codes")
    total = inputs.astype(np.int64) @ weights.astype(np.int64) + bias.astype(np.int64)
    sign = 1 << 35
    acc = ((total + sign) % (2 * sign)) - sign
    result = np.zeros((99, 256), dtype="<i2")
    for shift in range(13, 19):
        cols = shifts == shift
        value = acc[:, cols]
        quotient = value >> shift
        remainder = value - (quotient << shift)
        half = 1 << (shift - 1)
        rounded = quotient + ((remainder > half) | ((remainder == half) & ((quotient & 1) != 0)))
        result[:, cols] = np.clip(rounded, -32768, 32767)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codes", help="NPZ with input, weight, bias, shift")
    parser.add_argument("output", help="Output little-endian signed int16 binary, row-major")
    args = parser.parse_args()
    with np.load(args.codes, allow_pickle=False) as data:
        reference(*(data[key] for key in ("input", "weight", "bias", "shift"))).tofile(args.output)


if __name__ == "__main__":
    main()

