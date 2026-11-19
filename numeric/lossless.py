"""Lossless 32-bit wire encoding for the two-page INT16 task."""

from collections import deque


def signed(value, bits):
    return (value ^ (1 << (bits - 1))) - (1 << (bits - 1))


def rice(value, k, escape=None):
    u = 2 * value if value >= 0 else -2 * value - 1
    q = u >> k
    if escape is not None and q >= escape:
        return ((u << escape) | ((1 << escape) - 1), 16 + escape)
    return (((u & ((1 << k) - 1)) << (q + 1)) | ((1 << q) - 1), q + 1 + k)


def words(fields):
    reservoir = size = 0
    packed = []
    for value, width in fields:
        reservoir |= value << size
        size += width
        while size >= 32:
            packed.append(reservoir & 0xffffffff)
            reservoir >>= 32
            size -= 32
    if size:
        packed.append(reservoir)
    return packed


def predictor(row):
    if row >= 96:
        return row - 1
    return (row // 8) * 8 + (-1, 0, 1, 2, 1, 4, 5, 6)[row % 8]


def pack_input(values, identities):
    def fields(k):
        seen = {}
        for value, (row, inner) in zip(values, identities):
            if row == 0:
                yield value & 65535, 16
            else:
                delta = signed((value - seen[predictor(row), inner]) & 65535, 16)
                yield rice(delta, k, 15)
            seen[row, inner] = value

    best = None
    for k in (10, 11):
        codes = list(fields(k))
        packed = words(codes)
        cost = sum(width for _, width in codes)
        if best is None or cost < best[0]:
            split = 1 + (sum(width for _, width in codes[:2048]) + 31) // 32
            best = cost, [k | (len(packed) << 4) | (split << 17)] + packed, split
    return best[1], best[2]


def pack_tile(raw):
    biases = [signed(value, 32) for value in raw[:16]]
    shifts = [signed((value >> bit) & 255, 8) for value in raw[16:20] for bit in range(0, 32, 8)]
    bias_bits = max(1 + (value if value >= 0 else ~value).bit_length() for value in biases)
    shift_base = min(shifts)
    shift_bits = (max(shifts) - shift_base).bit_length()
    weight_words = words(rice(signed((value >> bit) & 65535, 16), 13)
                         for value in raw[20:] for bit in (0, 16))
    header = (len(weight_words) | ((bias_bits - 1) << 10) | ((shift_base & 255) << 15) |
              (shift_bits << 23) | (13 << 27))
    return [header] + words((v & ((1 << bias_bits) - 1), bias_bits) for v in biases) + \
        words((v - shift_base, shift_bits) for v in shifts) + weight_words


class Decoder:
    """One symbol per edge, up to 64 reservoir bits and two completed words."""

    def __init__(self, is_input, identities=()):
        self.is_input = is_input
        self.identities = identities
        self.previous = {}
        self.buffer = self.bits = self.symbol = self.partial = 0
        self.words_in = 0
        self.word_limit = None
        self.stalls = 0
        self.output = deque()
        self.total_symbols = len(identities) if is_input else 1056

    def feed(self, word):
        if self.word_limit is None:
            if self.is_input:
                self.k = word & 15
                self.word_limit = (word >> 4) & 8191
            else:
                self.bias_bits = ((word >> 10) & 31) + 1
                self.shift_base = signed((word >> 15) & 255, 8)
                self.shift_bits = (word >> 23) & 15
                self.k = (word >> 27) & 15
                self.word_limit = ((16*self.bias_bits + 31)//32 + (16*self.shift_bits + 31)//32 +
                                   (word & 1023))
            return
        assert self.bits <= 32 and self.words_in < self.word_limit
        self.buffer |= word << self.bits
        self.bits += 32
        self.words_in += 1

    def take(self, size):
        value = self.buffer & ((1 << size) - 1)
        self.buffer >>= size
        self.bits -= size
        return value

    def rice_size(self, cap):
        low = self.buffer & ((1 << min(cap, self.bits)) - 1)
        q = (low ^ (low + 1)).bit_length() - 1
        if q == cap and self.bits >= cap and self.is_input:
            return cap + 16, cap, True
        return q + 1 + self.k, q, False

    def step(self):
        if self.word_limit is None or self.symbol == self.total_symbols or len(self.output) == 2:
            return
        index = self.symbol
        if self.is_input:
            row, inner = self.identities[index]
        raw_input = self.is_input and row == 0
        if raw_input:
            size, group = 16, 2
        elif not self.is_input and index < 32:
            size, group = (self.bias_bits, 1) if index < 16 else (self.shift_bits, 4)
        else:
            size, q, escaped = self.rice_size(15 if self.is_input else 8)
            group = 2
        pad = 0
        if not self.is_input and index in (15, 31):
            pad = (-16 * size) % 32
        if self.bits < size + pad:
            self.stalls += 1
            return
        code = self.take(size)
        if pad:
            assert self.take(pad) == 0
        if raw_input:
            value = signed(code, 16)
        elif not self.is_input and index < 32:
            value = signed(code, size) if index < 16 else code + self.shift_base
        else:
            u = (code >> q) if escaped else (q << self.k) | (code >> (q + 1))
            value = (u >> 1) ^ -(u & 1)
            if self.is_input:
                value = signed((value + self.previous[predictor(row), inner]) & 65535, 16)
        if self.is_input:
            self.previous[row, inner] = value
        width = 32 // group
        self.partial |= (value & ((1 << width) - 1)) << (width * (index % group))
        if index % group == group - 1:
            self.output.append(self.partial)
            self.partial = 0
        self.symbol += 1
