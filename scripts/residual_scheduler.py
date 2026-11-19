"""Exact row-group scheduler and compatible register-address streaming adapter."""
import re
from ffn_residual import ROOT


def core(m):
    parent=(ROOT/m['parent']['source_snapshot']/'encoder/kwt_encoder.sv').read_text()
    header=parent[:min(parent.index('    localparam integer TILES'),parent.find('    localparam integer ROW_GROUP') if '    localparam integer ROW_GROUP' in parent else len(parent))]
    f=m['features'];e=m['effective_changes'];c=m['changes'];stream=bool(e.get('stream'))
    group=e.get('row_group',2 if e.get('row_pair') else 1)
    depth=int(re.search(r'fifo\[0:(\d+)\]',parent).group(1))+1
    bias_banks=4 if e.get('bias32') else 8 if 'compact_bias_banks' in parent else 16 if f['lanes16'] else 8
    clear=re.search(r'CLEAR: if\(clear_index==(\d+)\)',parent)
    values=dict(ROW_GROUP=group,SLOTS=2 if e.get('double_buffer') else 1,STREAM=int(stream),SMALL=int(e.get('small_input',False)),
        USE_CACHE=int(stream or e.get('row_cache',False)),ZERO=int(e.get('zero_clear',False)),BIAS32=int(e.get('bias32',False)),BIAS_BANKS=bias_banks,
        FIFO_LAST=depth-1,FIFO_DEPTH=depth,PTR_LAST=(depth-1).bit_length()-1,PTR_BITS=(depth-1).bit_length(),
        COUNT_LAST=depth.bit_length()-1,COUNT_BITS=depth.bit_length(),CLEAR_LAST=int(clear.group(1)) if clear else 0,
        FINE_REG=int(e.get('fine_register_gate',False)),
        MEM_TEST='.test_enable(clock_test_enable),' if e.get('fine_memory_gate') else '',
        WEIGHT_MODULE='kwt_adaptive_spmem16' if e.get('fine_memory_gate') else 'kwt_spmem16',
        WEIGHT_TEST='.test_enable(clock_test_enable),' if e.get('fine_memory_gate') else '')
    text=(ROOT/'rtl/ffn/kwt_ffn_residual_body.svh').read_text()
    for key,value in values.items():text=text.replace('@'+key+'@',str(value))
    return header+text


def bus(m):
    text=(ROOT/m['parent']['source_snapshot']/'encoder_bus/kwt_icb_encoder.sv').read_text()
    if not m['changes'].get('stream') or '    reg stream_mode;' in text:return text
    text=text.replace('reg linear_mode,pack_pending;','reg linear_mode,pack_pending;\n    reg stream_mode;')
    text=text.replace("8'h2c: icb_rsp_rdata<={31'b0,linear_mode};","8'h2c: icb_rsp_rdata<={30'b0,stream_mode,linear_mode};")
    text=text.replace("8'h2c: stored_rsp_rdata<={31'b0,linear_mode};","8'h2c: stored_rsp_rdata<={30'b0,stream_mode,linear_mode};")
    text=text.replace("immediate_data={31'b0,linear_mode};","immediate_data={30'b0,stream_mode,linear_mode};")
    text=text.replace('if(!(core_start_ready&&icb_cmd_wdata<2))immediate_error=1;', 'if(!(core_start_ready&&icb_cmd_wdata==3))immediate_error=1;')
    text=text.replace('if(core_start_ready&&icb_cmd_wdata<2) linear_mode<=icb_cmd_wdata[0];','if(core_start_ready&&icb_cmd_wdata==3) begin linear_mode<=1;stream_mode<=1;end')
    text=text.replace('linear_mode<=0;', 'linear_mode<=0;stream_mode<=0;')
    text=text.replace("8'h2c: if(core_start_ready&&icb_cmd_wdata<2) linear_mode<=icb_cmd_wdata[0]; else icb_rsp_err<=1;",
        "8'h2c: if(core_start_ready&&icb_cmd_wdata==3) begin linear_mode<=1;stream_mode<=1;end else icb_rsp_err<=1;")
    return text
