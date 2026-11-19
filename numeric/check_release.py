"""Regenerate all submission payloads and compare every output code."""
import argparse
from pathlib import Path

from convert import convert

ROOT = Path(__file__).resolve().parents[1]
SOC = ROOT / "build/optimization/complete_soc/ffn_ag_mgpr"
EXPECTED = ROOT / "build/optimization/ffn_ar_area/frozen/images"


def compare(actual, expected):
    actual_lines = actual.read_text(encoding="ascii").splitlines()
    if actual_lines != expected.read_text(encoding="ascii").splitlines():
        raise ValueError("Mismatch: " + str(expected))
    return len(actual_lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/reproduction/numeric")
    args = parser.parse_args()
    total = 0
    for layer in range(12):
        number = layer + 1
        case = 2 * layer + 1
        fixture = ROOT / "numeric" / "fixtures" / ("layer_%02d_float.npz" % layer)
        output = args.out / ("case_%02d" % case)
        convert(fixture, output, layer)
        for name in ("addresses", "payload", "count"):
            compare(output / (name + ".hex"), SOC / "packed_inputs" /
                    ("task_%02d_%s.hex" % (number, name)))
        count = compare(output / "expected.hex", EXPECTED / ("task_%02d_expected.hex" % case))
        total += count
        loaded = int((output / "count.hex").read_text(), 16)
        print("case=%02d layer=%02d load_words=%d outputs=%d PASS" % (case, layer, loaded, count))
    print("NUMERIC_PASS cases=12 outputs=%d" % total)


if __name__ == "__main__":
    main()

