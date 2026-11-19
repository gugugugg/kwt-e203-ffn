"""Materialize the one authorized32MAC child of frozen IR, retaining16 banks."""
from pathlib import Path
import json
import shutil

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT/'build/optimization/ffn_column_parallel'
REPORT = ROOT/'reports/optimization/ffn_column_parallel'
NAME = 'ffn_cp_C16'


def transform(text):
    changes = [
        ('localparam integer TILES=32,GROUPS=1;', 'localparam integer TILES=16,GROUPS=1,MAC_LANES=32,MAC_COLUMNS=16;'),
        ('reg [4:0] tile;', 'reg [3:0] tile;'),
        ('reg [2:0] lane;', 'reg [3:0] lane;'),
        ('reg [1:0] chunk;', 'reg [2:0] chunk;'),
        ('accumulator[0:15]', 'accumulator[0:MAC_LANES-1]'),
        ('shifts[0:15]', 'shifts[0:MAC_LANES-1]'),
        ('tile<31', 'tile<15'), ('tile==31', 'tile==15'),
        ('lane<6', 'lane<14'), ('lane==6', 'lane==14'),
        ("wire [4:0] ap_er_target_tile=tile==15?5'd0:tile+5'd1;", "wire [3:0] ap_er_target_tile=tile==15?4'd0:tile+4'd1;"),
        ("wire [1:0] ap_er_request_pair=ap_er_first_request?2'd0:lane[2:1]+2'd1;", "wire [2:0] ap_er_request_pair=ap_er_first_request?3'd0:lane[3:1]+3'd1;"),
        ('wire [4:0] ap_bias_tile=', 'wire [3:0] ap_bias_tile='),
        ('wire [1:0] ap_bias_pair=', 'wire [2:0] ap_bias_pair='),
        ('wire [15:0] jp_seed_mask,jp_mac_mask,jp_quant_mask;', 'wire [MAC_LANES-1:0] jp_seed_mask,jp_mac_mask,jp_quant_mask;'),
        ('tile[4:1]', 'tile'),
        ("int'(ap_bias_tile)*32", "int'(ap_bias_tile)*64"),
        ('reg [31:0] jp_input_return;', 'reg [63:0] jp_input_return;'),
        ('''        wire lp_return_clock;
        kwt_ffn_clock_gate return_gate(.clk(clk),.enable(read_enable),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(lp_return_clock));
        always_latch if(lp_return_clock)jp_input_return[ap_row*16+:16]<=ap_input_rdata[ap_row*16+:16];''',
         '''        for(genvar cp_copy=0;cp_copy<2;cp_copy=cp_copy+1)begin: return_copies
            wire lp_return_clock;
            kwt_ffn_clock_gate return_gate(.clk(clk),.enable(read_enable),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(lp_return_clock));
            always_latch if(lp_return_clock)jp_input_return[(ap_row*2+cp_copy)*16+:16]<=ap_input_rdata[ap_row*16+:16];
        end'''),
        ('wire [3:0] jp_quant_lane=', 'wire [4:0] jp_quant_lane='),
        ("{1'b0,jp_quant_lane}+5'd1", "{1'b0,jp_quant_lane}+6'd1"),
        ('jp_lane<16', 'jp_lane<MAC_LANES'),
        ('jp_row=jp_lane/8', 'jp_row=jp_lane/MAC_COLUMNS'),
        ('jp_column=jp_lane%8', 'jp_column=jp_lane%MAC_COLUMNS'),
        ("chunk==2'(jp_column/2)", "chunk==3'(jp_column/2)"),
        ("lane[2:1]==2'(jp_column/2)", "lane[3:1]==3'(jp_column/2)"),
        ('jp_input_return[jp_row*16+:16]', 'jp_input_return[(jp_row*2+jp_column/8)*16+:16]'),
        ("pm_rdata[(int'(tile[0])*8+jp_column)*16+:16]", 'pm_rdata[jp_column*16+:16]'),
        ("for(b=0;b<LANES;b=b+1)if((b/8)==int'(tile[0]))begin", 'for(b=0;b<LANES;b=b+1)begin'),
        ("int'(ap_bias_tile)*4", "int'(ap_bias_tile)*8"),
        ('BIAS_CAP:if(chunk==3)', 'BIAS_CAP:if(chunk==7)'),
        ("lane<=lane+3'd2", "lane<=lane+4'd2"),
    ]
    for old, new in changes:
        if old not in text: raise ValueError('Frozen IR transform anchor missing: '+old)
        text = text.replace(old, new)
    return text


def prepare():
    parent = json.loads((BUILD/'frozen/parent.json').read_text())
    target = ROOT/'build/optimization/rtl_sources'/NAME
    target.mkdir(parents=True, exist_ok=True)
    for path in (BUILD/'frozen/rtl_sources').rglob('*'):
        if path.is_file():
            dest = target/path.relative_to(BUILD/'frozen/rtl_sources')
            dest.parent.mkdir(parents=True, exist_ok=True)
            if path.name != 'kwt_encoder.sv': shutil.copyfile(str(path), str(dest))
    core = target/'encoder/kwt_encoder.sv'
    core.write_text(transform((BUILD/'frozen/rtl_sources/encoder/kwt_encoder.sv').read_text()))
    manifest = dict(variant=NAME, parent_variant='ffn_lp_IR', parent=parent,
        features=parent['features'], effective_changes=dict(parent['effective_changes'],column_parallel_hardware=['C16'],
        compute_lanes=32,compute_columns=16,weight_banks=16,row_group=2),
        changes=dict(stream=True,small_input=True,row_group=2,double_buffer=True),layout=parent['layout'],
        dma=True,output_dma=True,flook=parent['flook'],hardware=['S','H','M2','IR','C16'],
        column_parallel_hardware=['C16'],purpose='experiment',pio_program=parent['pio_program'],
        compiler=parent['compiler'],loader='required_data_v1',numerical_package='models/kwt_unified_optimized_v1',
        objective=['complete_acceptance','energy_below_IR','area_at_most_125pct_IR','throughput_at_least_1000'],
        automatic_release_switch=False)
    path = ROOT/'constraints/ffn_column_parallel/candidates'/ (NAME+'.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2))
    shutil.copyfile(str(path), str(REPORT/'candidate.json'))
    return manifest, target


if __name__ == '__main__':
    prepare()
    print('COLUMN_PARALLEL_PREPARED', NAME)
