"""Convert one layer's FC1 operands to the exact submitted host image."""
import argparse
import json
from pathlib import Path

import numpy as np

from fixed_reference import reference
from lossless import pack_input, pack_tile


def scale_config(layer):
    config = Path(__file__).with_name("q2_scales.json")
    return json.loads(config.read_text(encoding="utf-8"))["layers"][layer]


def encode_floats(inputs, weights, bias, layer):
    inputs, weights, bias = (np.asarray(a, dtype=np.float64) for a in (inputs, weights, bias))
    if (inputs.shape, weights.shape, bias.shape) != ((99, 64), (64, 256), (256,)):
        raise ValueError("Expected input[99,64], weight[64,256], bias[256]")
    if any(not np.isfinite(a).all() for a in (inputs, weights, bias)):
        raise ValueError("Floating operands must be finite")
    config = scale_config(layer)
    fi, fa, fo = (np.asarray(config[key]) for key in ("input_f", "accumulator_f", "output_f"))
    x = np.clip(np.rint(np.ldexp(inputs, fi)), -32768, 32767).astype("<i2")
    w = np.clip(np.rint(np.ldexp(weights, fa[None, :] - fi[:, None])), -32768, 32767).astype("<i2")
    b = np.rint(np.ldexp(bias, fa))
    if np.any(b < -(1 << 31)) or np.any(b >= (1 << 31)):
        raise ValueError("Compact bias requires the upper 32 bits to be sign extension")
    return x, w, b.astype("<i4"), (fa - fo).astype("i1")


def pack_words(values, bits):
    values = np.asarray(values).reshape(-1).astype(np.uint32)
    groups = values.reshape(-1, 32 // bits) & np.uint32((1 << bits) - 1)
    shifts = np.arange(0, 32, bits, dtype=np.uint32)
    return np.bitwise_or.reduce(groups << shifts, axis=1)


def pack_payload(inputs, weights, bias, shifts):
    identities = [(row, k) for first in range(0, 96, 8) for k in range(64)
                  for row in (first, first+1, first+4, first+5, first+2, first+3, first+6, first+7)]
    identities.extend((row, k) for k in range(64) for row in range(96, 99))
    packed, split = pack_input([int(inputs[row, k]) for row, k in identities], identities)
    image = dict(enumerate(packed))
    tiles = []
    last = 32768
    for col in range(0, 256, 16):
        raw = np.concatenate((bias[col:col+16].astype(np.uint32),
                              pack_words(shifts[col:col+16], 8),
                              pack_words(weights[:, col:col+16], 16)))
        tile = pack_tile([int(word) for word in raw])
        indices = list(range(last, last+len(tile)))
        image.update(zip(indices, tile))
        tiles.append(indices)
        last += len(tile)
    order = [0] + tiles[0] + list(range(1,split)) + tiles[1] + list(range(split,len(packed)))
    order.extend(i for tile in tiles[2:] for i in tile)
    return np.array(order), np.array([image[i] for i in order], dtype=np.uint32)


def write_hex(path, data, digits):
    mask = (1 << (digits * 4)) - 1
    with path.open("w", encoding="ascii", newline="\n") as out:
        out.writelines(("{:0" + str(digits) + "x}\n").format(int(value) & mask)
                       for value in data.reshape(-1))


def convert(source, output, layer, encoded=False):
    with np.load(source, allow_pickle=False) as data:
        if encoded:
            arrays = tuple(data[key] for key in ("input", "weight", "bias", "shift"))
        else:
            arrays = encode_floats(*(data[key] for key in ("input", "weight", "bias")), layer)
    codes = reference(*arrays)
    addresses, payload = pack_payload(*arrays)
    output.mkdir(parents=True, exist_ok=True)
    write_hex(output / "addresses.hex", addresses, 5)
    write_hex(output / "payload.hex", payload, 8)
    write_hex(output / "count.hex", np.array([len(payload)]), 8)
    write_hex(output / "expected.hex", codes, 4)
    codes.tofile(output / "output_codes.bin")
    decoded = np.ldexp(codes.astype(np.float64), -np.asarray(scale_config(layer)["output_f"]))
    np.save(output / "output_decoded.npy", decoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="NPZ with input, weight, bias; also shift if encoded")
    parser.add_argument("--layer", type=int, choices=range(12), required=True, help="Zero-based FC1 layer")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--encoded", action="store_true", help="Input NPZ contains integer codes")
    args = parser.parse_args()
    convert(args.source, args.out, args.layer, args.encoded)


if __name__ == "__main__":
    main()

