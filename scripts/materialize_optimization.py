"""Emit a separate source snapshot for each independently measured RTL configuration."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = {'baseline': [], 'M': ['MEMORY'], 'P': ['PIPE'], 'O': ['OUTPUT'],
            'D': ['DIV'], 'combined': ['MEMORY', 'PIPE', 'OUTPUT', 'DIV'],
            'combined_Q': ['MEMORY', 'PIPE', 'OUTPUT', 'DIV'],
            'combined_QG': ['MEMORY', 'PIPE', 'OUTPUT', 'DIV', 'ISOLATE'],
            'ffn_logic_Q': ['PIPE', 'OUTPUT'], 'ffn_compact_Q': ['PIPE', 'OUTPUT']}
FFN_ROUND2 = {
    'ffn_v2_M': {'SMALL_SHIFT': 1},
    'ffn_v2_W': {'ACC_WIDTH': 36},
    'ffn_v2_Q': {'NARROW_QUANT': 1},
    'ffn_v2_P': {'PIPE_MAC': 1},
    'ffn_v2_F': {'STREAM_OUTPUT': 1},
    'ffn_v2_R2': {'ROW_PAIR': 1},
    'ffn_v2_MWQP': {'SMALL_SHIFT': 1, 'ACC_WIDTH': 36, 'NARROW_QUANT': 1, 'PIPE_MAC': 1},
    'ffn_v2_MWQPF': {'SMALL_SHIFT': 1, 'ACC_WIDTH': 36, 'NARROW_QUANT': 1, 'PIPE_MAC': 1, 'STREAM_OUTPUT': 1}}
VARIANTS.update({name: ['PIPE', 'OUTPUT'] for name in FFN_ROUND2})
from ffn_round3_config import CANDIDATES as FFN_ROUND3
VARIANTS.update({name: ['PIPE', 'OUTPUT'] for name in FFN_ROUND3})


def prepare(variant):
    if variant in FFN_ROUND3:
        from materialize_ffn_round3 import prepare as prepare_round3
        return prepare_round3(variant)
    active = {'KWT_OPT_' + s for s in VARIANTS[variant]}
    out = ROOT / 'build/optimization/rtl_sources' / variant
    for directory in ['encoder', 'encoder_bus']:
        (out / directory).mkdir(parents=True, exist_ok=True)
        for source in (ROOT / 'rtl' / directory).glob('*'):
            if not source.is_file():
                continue
            lines, states = [], []
            for line in source.read_text().splitlines(keepends=True):
                stripped = line.strip()
                if stripped.startswith('`ifdef KWT_OPT_'):
                    states.append(stripped.split()[1] in active)
                elif stripped == '`else' and states:
                    states[-1] = not states[-1]
                elif stripped == '`endif' and states:
                    states.pop()
                elif all(states):
                    lines.append(line)
            (out / directory / source.name).write_text(''.join(lines))
    if variant in FFN_ROUND2:
        text = (ROOT / 'rtl/ffn/kwt_ffn_optimized.sv').read_text().replace('module kwt_ffn_optimized #(', 'module kwt_encoder #(')
        for name, value in FFN_ROUND2[variant].items():
            text = text.replace(name + '=' + ('64' if name == 'ACC_WIDTH' else '0'), name + '=' + str(value))
        (out / 'encoder/kwt_encoder.sv').write_text(text)
        (out / 'encoder/kwt_ffn_requantize.sv').write_text((ROOT / 'rtl/ffn/kwt_ffn_requantize.sv').read_text())
    elif variant.startswith('ffn_'):
        text = (ROOT / 'rtl/ffn/kwt_ffn_core.sv').read_text().replace('module kwt_ffn_core #(', 'module kwt_encoder #(')
        text = text.replace('parameter integer COMPACT=0', 'parameter integer COMPACT=%d' % (variant == 'ffn_compact_Q'))
        (out / 'encoder/kwt_encoder.sv').write_text(text)
    (out / 'configuration.json').write_text(json.dumps({'variant': variant, 'optimizations': VARIANTS[variant],
                                                     'ffn_parameters': FFN_ROUND2.get(variant, {})}, indent=2))
    return out


if __name__ == '__main__':
    for variant in VARIANTS:
        print(prepare(variant))
