"""Materialize round-three sources without touching any round-two snapshots."""
from pathlib import Path
import json
import shutil
from ffn_round3_config import ROOT, CANDIDATES, freeze, copy_tree


def prepare(variant):
    baseline = freeze()
    features = CANDIDATES[variant]
    out = ROOT / 'build/optimization/rtl_sources' / variant
    copy_tree(baseline / 'rtl_sources', out)
    source = (ROOT / 'rtl/ffn/kwt_ffn_round3.sv').read_text()
    source = source.replace('module kwt_ffn_round3 #(', 'module kwt_encoder #(')
    source = source.replace('SPLIT_BIAS=1', 'SPLIT_BIAS=%d' % features['split_bias'])
    for symbol, value in [('FAST_PAIR', features['fast_pair']), ('OVERLAP', features['overlap']),
                          ('CLOCK_GATING', features['clock_gating'])]:
        source = source.replace(symbol + '=0', symbol + '=%d' % value)
    source = source.replace('LANES=8', 'LANES=%d' % (16 if features['lanes16'] else 8))
    if variant == 'ffn_v3_U':
        # U is a firmware-only ablation of the exact accepted RTL.
        pass
    else:
        (out / 'encoder/kwt_encoder.sv').write_text(source)
        shutil.copy2(ROOT / 'rtl/ffn/kwt_ffn_clock_gate.sv', out / 'encoder/kwt_ffn_clock_gate.sv')
        if features['clock_gating']:
            memory = out / 'encoder/kwt_encoder_memory.sv'
            text = memory.read_text().replace('kwt_spmem16 #',
                'wire bank_clk;\n        kwt_ffn_clock_gate gate(.clk(clk),.enable(en[b]),.test_enable(1\'b0),.gated_clk(bank_clk));\n        kwt_spmem16 #')
            text = text.replace('.clk(clk),.en(en[b])', '.clk(bank_clk),.en(en[b])')
            memory.write_text(text)
        bus = out / 'encoder_bus/kwt_icb_encoder.sv'
        text = bus.read_text()
        text = text.replace('.linear_mode(linear_mode),', '.linear_mode(linear_mode),.clock_test_enable(1\'b0),')
        text = text.replace('wire core_busy,', 'wire core_pair_valid;\n    wire signed [15:0] core_out_high;\n    wire core_busy,')
        fast = features['fast_pair']
        text = text.replace('wire read_pair=icb_cmd_read', 'wire read_pair=icb_cmd_read')
        if fast:
            text = text.replace('wire pair_second=output_pair_pending&&core_out_valid;', 'wire pair_second=1\'b0;')
            text = text.replace('wire pair_wait=output_pair_pending;', 'wire pair_wait=1\'b0;')
            text = text.replace('(!(read_output||read_pair)||core_out_valid||core_error||bus_error||done_sticky)',
                '(!read_output||core_out_valid||core_error||bus_error||done_sticky)&&\n                         (!read_pair||core_pair_valid||core_error||bus_error||done_sticky)')
            text = text.replace('wire packed_load=fire', 'wire packed_load=fire')
            text = text.replace('wire pop_output=(fire&&(read_output||read_pair)&&core_out_valid)',
                                'wire pop_output=(fire&&read_output&&core_out_valid)')
            text = text.replace('.load_addr(load_address),.load_data(core_load_data),',
                '.load_addr(load_address),.load_data(core_load_data),\n        .load_pair(packed_load&&load_kind!=5),.load_high(icb_cmd_wdata[31:16]),')
            text = text.replace('if(do_load) load_address<=load_address+1\'b1;',
                'if(do_load) load_address<=load_address+((packed_load&&load_kind!=5)?16\'d2:16\'d1);')
            text = text.replace('output_low<=core_out_data;output_pair_pending<=1;icb_rsp_valid<=0;',
                                'icb_rsp_rdata<={core_out_high,core_out_data};')
            text = text.replace('if(packed_load) begin packed_high<=icb_cmd_wdata[31:16]; pack_pending<=1; end',
                                'if(packed_load) begin packed_high<=icb_cmd_wdata[31:16]; pack_pending<=load_kind==5; end')
        else:
            text = text.replace('.load_addr(load_address),.load_data(core_load_data),',
                                '.load_addr(load_address),.load_data(core_load_data),.load_pair(1\'b0),.load_high(16\'b0),')
        text = text.replace('.out_valid(core_out_valid),.out_ready(pop_output),',
            '.out_valid(core_out_valid),.out_ready(pop_output),\n        .out_pair_valid(core_pair_valid),.out_high(core_out_high),\n        .out_pair_ready(%s),' % ('fire&&read_pair&&core_pair_valid' if fast else "1'b0"))
        bus.write_text(text)
    (out / 'configuration.json').write_text(json.dumps({'variant': variant, 'features': features,
        'frozen_baseline': str(baseline.relative_to(ROOT)), 'optimizations': ['PIPE', 'OUTPUT']}, indent=2))
    return out


if __name__ == '__main__':
    import sys
    for name in sys.argv[1:] or CANDIDATES:
        print(prepare(name))
