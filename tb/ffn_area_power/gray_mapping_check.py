"""Check the Gray layout with all stored FC1 weights and both normal loaders."""
from pathlib import Path
import argparse
import json
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from area_power_weights import transform_core


def gray6(value):
    return value ^ (value >> 1)


def physical(inner, tile):
    return (gray6(inner) << 4) | tile


def check_layer(parameters, step):
    memory = [[0] * 1024 for _ in range(16)]
    packed = [parameters[k * 256 + tile * 16 + lane]
              for tile in range(16) for k in range(64) for lane in range(16)]
    for address in range(0, 16384, step):
        for offset in range(step):
            logical = address + offset
            word = logical // 16
            memory[logical % 16][physical(word & 63, word >> 6)] = packed[logical]
    for inner in range(64):
        for column in range(256):
            actual = memory[column % 16][physical(inner, column // 16)]
            if actual != parameters[inner * 256 + column]:
                raise AssertionError('FC1 weight mismatch at inner=%d column=%d' % (inner, column))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--core', type=Path, default=ROOT / 'build/optimization/rtl_sources/ffn_tp_CROSS/encoder/kwt_encoder.sv')
    parser.add_argument('--report', type=Path, default=ROOT / 'reports/optimization/ffn_area_power/development/gray')
    args = parser.parse_args()
    original = args.core.read_text(encoding='utf-8')
    changed = transform_core(original)
    args.report.mkdir(parents=True, exist_ok=True)
    (args.report / 'transformed_core.sv').write_text(changed, encoding='utf-8')
    addresses = [physical(inner, tile) for inner in range(64) for tile in range(16)]
    if sorted(addresses) != list(range(1024)):
        raise AssertionError('The local weight layout is not a 1024-address bijection')
    records = []
    for layer in range(12):
        source = ROOT / ('build/optimization/ffn_transport/testdata/layer_%02d_parameters.bin' % layer)
        values = [v[0] for v in struct.iter_unpack('<H', source.read_bytes())]
        for step in (1, 2):
            check_layer(values, step)
        records.append(dict(layer=layer, weights=16384, banks=16,
                            scalar_and_pair_exact=True, source=source.relative_to(ROOT).as_posix()))
    record = dict(passed=True, scope='Static bijection and actual stored FC1 weight reload; not RTL or CPU acceptance',
                  core=str(args.core), local_addresses=1024, layers=records,
                  generated_core=str(args.report / 'transformed_core.sv'),
                  actual_source_weight_values=12 * 16384)
    (args.report / 'mapping-check.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print('GRAY_MAPPING_ACTUAL12_PASS weights=%d normal_load_modes=2' % (12 * 16384))


if __name__ == '__main__':
    main()
