"""Bit-defined signed integer operations used by the numerical model and RTL vectors."""

from math import isqrt

import numpy as np


def round_shift(value, shift):
    """Round signed integers / 2**shift to nearest, ties to even; negative = left shift."""
    value = np.asarray(value, dtype=np.int64)
    if shift < 0:
        if shift < -30 or int(np.abs(value).max(initial=0)) > ((1 << 62) >> -shift):
            raise OverflowError('Unsafe integer left shift.')
        return value << -shift
    if shift == 0:
        return value.copy()
    if shift > 62:
        raise ValueError('Right shift outside the supported int64 range.')
    quotient = value >> shift
    remainder = value - (quotient << shift)
    halfway = 1 << (shift - 1)
    return quotient + ((remainder > halfway) | ((remainder == halfway) & ((quotient & 1) != 0)))


def round_divide(numerator, denominator):
    """Signed numerator, positive denominator, Euclidean remainder, ties to even."""
    numerator = np.asarray(numerator, dtype=np.int64)
    denominator = np.asarray(denominator, dtype=np.int64)
    if np.any(denominator <= 0):
        raise ValueError('The divisor must be positive.')
    quotient = numerator // denominator
    remainder = numerator - quotient * denominator
    return quotient + ((remainder * 2 > denominator) |
                       ((remainder * 2 == denominator) & ((quotient & 1) != 0)))


def saturate16(value, stats=None, name=''):
    value = np.asarray(value, dtype=np.int64)
    if stats is not None:
        record = stats.setdefault(name, {'elements': 0, 'saturated': 0})
        record['elements'] += int(value.size)
        record['saturated'] += int(np.count_nonzero((value < -32768) | (value > 32767)))
    return np.clip(value, -32768, 32767).astype('<i2')


def encode(value, fractional_bits, stats=None, name=''):
    value = np.asarray(value)
    if not np.isfinite(value).all():
        raise ValueError('Input encoding requires finite values.')
    scaled = np.rint(value.astype(np.float64) * (2.0 ** fractional_bits))
    if stats is not None:
        record = stats.setdefault(name, {'elements': 0, 'saturated': 0})
        record['elements'] += int(scaled.size)
        record['saturated'] += int(np.count_nonzero((scaled < -32768) | (scaled > 32767)))
    return np.clip(scaled, -32768, 32767).astype('<i2')


def decode(value, fractional_bits):
    return np.asarray(value).astype(np.float64) * (2.0 ** -fractional_bits)


def exact_dot(a, b, backend='int64'):
    """Exact mathematical integer GEMM, with int64 accumulator bound checked.

    exact-f64 accelerates only when every product and every possible partial sum
    is an exactly representable integer <=2**53. Floating division is never used.
    """
    a, b = np.asarray(a), np.asarray(b)
    if a.dtype.kind not in 'iu' or b.dtype.kind not in 'iu':
        raise TypeError('Integer GEMM requires integer inputs.')
    bound = int(np.abs(a.astype(np.int64)).max(initial=0)) * int(
        np.abs(b.astype(np.int64)).max(initial=0)) * a.shape[-1]
    if bound > (1 << 62):
        raise OverflowError('Integer accumulator bound exceeded.')
    if backend == 'int64':
        return a.astype(np.int64) @ b.astype(np.int64)
    if backend == 'exact-f64':
        if bound > (1 << 53):
            raise OverflowError('Cannot prove exact float64 representation of all integer partial sums.')
        return (a.astype(np.float64) @ b.astype(np.float64)).astype(np.int64)
    raise ValueError('Unknown GEMM backend: ' + backend)


def dense(x, weights, bias_accumulator, input_f, weight_f, output_f, backend, stats=None, name=''):
    accumulator = exact_dot(x, weights, backend)
    bias = np.asarray(bias_accumulator, dtype=np.int64)
    if int(np.abs(accumulator).max(initial=0)) + int(np.abs(bias).max(initial=0)) >= (1 << 62):
        raise OverflowError('Bias would overflow accumulator bound.')
    return saturate16(round_shift(accumulator + bias, input_f + weight_f - output_f), stats, name)


def residual(a, a_f, b, b_f, output_f, stats=None, name=''):
    common = max(a_f, b_f)
    total = round_shift(a, a_f - common) + round_shift(b, b_f - common)
    return saturate16(round_shift(total, common - output_f), stats, name)


def interpolate_lut(x_q16, table, low):
    """4097 nodes at 1/256 intervals, input Q16, output same code scale as table."""
    offset = np.clip(x_q16 - low * 65536, 0, 4096 * 256)
    index = np.minimum(offset >> 8, 4095)
    remainder = offset - (index << 8)
    a, b = table[index].astype(np.int64), table[index + 1].astype(np.int64)
    return round_shift(a * (256 - remainder) + b * remainder, 8)


def gelu(x, input_f, output_f, table, stats=None, name=''):
    x_q16 = round_shift(x, input_f - 16)
    values = interpolate_lut(x_q16, table, -8)
    values = np.where(x_q16 <= -8 * 65536, 0, values)
    values = np.where(x_q16 >= 8 * 65536, round_shift(x, input_f - 20), values)
    return saturate16(round_shift(values, 20 - output_f), stats, name)


def softmax(scores, score_f, exp_table):
    difference = scores - np.max(scores, axis=-1, keepdims=True)
    difference_q16 = round_shift(difference, score_f - 16)
    exponents = interpolate_lut(difference_q16, exp_table, -16)
    exponents = np.where(difference_q16 < -16 * 65536, 0, exponents)
    denominator = np.sum(exponents, axis=-1, keepdims=True, dtype=np.int64)
    return round_divide(exponents << 15, denominator).astype('<u2')


def layer_norm(x, input_f, gamma, gamma_f, beta, beta_f, output_f, stats=None, name=''):
    """N=64, epsilon=1/1000000; integer sqrt with 8 fractional bits, normalized Q20."""
    if x.shape[-1] != 64 or not 0 <= input_f <= 24:
        raise ValueError('LayerNorm requires 64 features and input fractional bits in [0,24].')
    x64 = x.astype(np.int64)
    centered = 64 * x64 - np.sum(x64, axis=-1, keepdims=True, dtype=np.int64)
    sum_squared = np.sum(centered * centered, axis=-1, dtype=np.int64)
    epsilon_numerator = (64 ** 3) << (2 * input_f)
    denominator = np.array([isqrt(((int(value) * 1000000 + epsilon_numerator) << 16) // 1000000)
                            for value in sum_squared.flat], dtype=np.int64).reshape(sum_squared.shape + (1,))
    normalized = round_divide(centered * (8 << 28), denominator)
    affine_f = 20 + gamma_f
    affine = normalized * gamma.astype(np.int64) + round_shift(beta, beta_f - affine_f)
    return saturate16(round_shift(affine, affine_f - output_f), stats, name)
