"""Build only the selected M3 result-retirement implementation."""
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
PARENT, NAME = 'ffn_r3o_stream', 'ffn_m3_retire'
REPORT = ROOT / 'reports/optimization' / NAME
SOURCE = ROOT / 'build/optimization/rtl_sources' / NAME
SOC = ROOT / 'build/optimization/complete_soc' / NAME
RTL_TEST = ROOT / 'build/optimization/rtl' / NAME
sys.path.insert(0, str(ROOT / 'scripts/r3o_stream'))
import build_candidate as stream
from prepare import replace


def ring(text, direct):
    text = replace(text, 'reg [1:0] held_count,pending_count,pending_row,retiring_row;',
        'reg [2:0] held_count;\n    reg [1:0] pending_count,pending_row,retiring_row;')
    text = replace(text, 'reg [15:0] held_low,held_high;',
        """reg [15:0] held_data[0:3];
    reg [1:0] held_head,held_tail;
    wire [1:0] held_head_next=held_head+2'd1;
    wire [1:0] held_tail_next=held_tail+2'd1;""")
    text = text.replace('held_count==2', "held_count>=3'd2")
    text = replace(text, 'assign out_data=held_low;\n    assign out_high=held_high;',
                   'assign out_data=held_data[held_head];\n    assign out_high=held_data[held_head_next];')
    text = replace(text, "wire [2:0] space=3'd2", "wire [2:0] space=3'd4")
    if direct:
        text = replace(text, '    wire drain0=(fifo_count!=0)&&(row0_count<128)&&!read0;\n'
                             "    wire row0_room=({1'b0,fifo_count}+6'd2<=6'd16+6'(drain0));",
            """    // Only old FIFO data may bypass an empty first-row stash.
    wire bypass0=can_read&&(next_row==0)&&(row0_count==0)&&
                 (pending_count==0)&&(fifo_count!=0);
    wire bypass_pair=bypass0&&(space>=3'd2)&&(fifo_count>=5'd2)&&
                     (next_item[7:0]!=8'hff);
    wire [1:0] bypass_count=bypass_pair?2'd2:(bypass0?2'd1:2'd0);
    wire [3:0] fifo_read_next=fifo_read+4'd1;
    wire drain0=(fifo_count!=0)&&(row0_count<128)&&!read0&&!bypass0;
    wire [1:0] fifo_consumed=bypass0?bypass_count:2'(drain0);
    wire row0_room=({1'b0,fifo_count}+6'd2<=6'd16+6'(fifo_consumed));""")
        text = replace(text, "            if(drain0)begin fifo_read<=fifo_read+1'b1;row0_write<=row0_write+1'b1;end\n"
                             "            fifo_count<=fifo_count+5'(row0_push?2:0)-5'(drain0);",
            """            if(fifo_consumed!=0)fifo_read<=fifo_read+4'(fifo_consumed);
            if(drain0)row0_write<=row0_write+1'b1;
            fifo_count<=fifo_count+5'(row0_push?2:0)-5'(fifo_consumed);""")
    text = replace(text, '    wire [1:0] remaining=held_count-pop_count;',
        ("""    wire [1:0] fill_count=bypass0?bypass_count:pending_count;
    wire [15:0] fill_low=bypass0?fifo[fifo_read]:returned_low;
    wire [15:0] fill_high=bypass0?fifo[fifo_read_next]:returned_high;""" if direct else
         """    wire [1:0] fill_count=pending_count;
    wire [15:0] fill_low=returned_low;
    wire [15:0] fill_high=returned_high;""") + """
    generate for(genvar slot=0;slot<4;slot=slot+1)begin: return_words
        always @(posedge clk or negedge rst_n)begin
            if(!rst_n)held_data[slot]<=0;
            else if(!restart)begin
                if(fill_count!=0&&held_tail==2'(slot))held_data[slot]<=fill_low;
                else if(fill_count==2&&held_tail_next==2'(slot))held_data[slot]<=fill_high;
            end
        end
    end endgenerate""")
    text = replace(text, '            held_low<=0;held_high<=0;',
                   '            held_head<=0;held_tail<=0;')
    text = replace(text, '            held_count<=0;pending_count<=0;retiring_row<=0;',
                   '            held_count<=0;pending_count<=0;retiring_row<=0;\n'
                   '            held_head<=0;held_tail<=0;')
    return replace(text, """            if(pop_count==1)held_low<=held_high;
            if(pending_count!=0)begin
                if(remaining==0)held_low<=returned_low;
                else held_high<=returned_low;
                if(pending_count==2)held_high<=returned_high;
            end
            held_count<=remaining+pending_count;""",
        """            // Capture the previous synchronous return before reserving this edge's read.
            held_head<=held_head+pop_count;
            held_tail<=held_tail+fill_count;
            held_count<=held_count-3'(pop_count)+3'(fill_count);""")


def native_observer(text, direct):
    core = 'dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core'
    q = core + '.output_queue'
    hook = '        $display("FFN_ROUND3_PHASE'
    display = '''        $display("M3_RETIRE_COUNTS paired_reads=%0d adjacent_pairs=%0d ring_peak=%0d reserved_peak=%0d direct_words=%0d stalls0=%0d stalls1=%0d stalls2=%0d",
            retire_pairs,retire_adjacent,retire_held_peak,retire_reserved_peak,retire_direct,
            retire_wait[0],retire_wait[1],retire_wait[2]);
'''
    text = replace(text, hook, display + hook)
    declarations = '''`ifndef KWT_UNIFIED_GATE
    integer retire_pairs=0,retire_adjacent=0,retire_direct=0;
    integer retire_held_peak=0,retire_reserved_peak=0;
    integer retire_wait[0:2];
    reg retire_previous_pair=0,retire_in_window=0;
`endif
'''
    text = replace(text, '    task put_word(', declarations + '    task put_word(')
    before_end = text.rindex('endmodule')
    observer = '''`ifndef KWT_UNIFIED_GATE
    always @(posedge system_clk)begin
        if(!rst_n||(activity_window&&!retire_in_window))begin
            retire_pairs=0;retire_adjacent=0;retire_direct=0;
            retire_held_peak=0;retire_reserved_peak=0;retire_previous_pair=0;
            retire_wait[0]=0;retire_wait[1]=0;retire_wait[2]=0;
        end else if(activity_window)begin
            if(@Q@.issue_count==2)begin
                retire_pairs=retire_pairs+1;
                if(retire_previous_pair)retire_adjacent=retire_adjacent+1;
            end
            retire_previous_pair=(@Q@.issue_count==2);
            if(retire_held_peak<int'(@Q@.held_count))retire_held_peak=int'(@Q@.held_count);
            if(retire_reserved_peak<int'(@Q@.held_count)+int'(@Q@.pending_count))
                retire_reserved_peak=int'(@Q@.held_count)+int'(@Q@.pending_count);
            @DIRECT@
            if(@CORE@.emission&&!@CORE@.jp_quant_commit)
                retire_wait[@CORE@.emit_row]=retire_wait[@CORE@.emit_row]+1;
        end
        retire_in_window=activity_window;
    end
`endif
'''.replace('@DIRECT@', 'retire_direct=retire_direct+int\'(@Q@.bypass_count);' if direct else '')
    return text[:before_end] + observer.replace('@CORE@', core).replace('@Q@', q) + text[before_end:]


def materialize():
    selection = json.loads((REPORT / 'model-selection.json').read_text())
    winner = selection['selected']
    if not selection['passed'] or winner not in ('R4', 'R4+F2'):
        raise RuntimeError('No eligible retirement implementation')
    direct = winner == 'R4+F2'
    previous = ROOT / 'constraints/ffn_selected.json'
    cfg = json.loads(previous.read_text())
    if cfg['variant'] != PARENT:
        raise RuntimeError('M3 is not the current release')
    (REPORT / 'baseline-selected.json').write_bytes(previous.read_bytes())
    if not SOURCE.exists():
        shutil.copytree(str(ROOT / cfg['source_snapshot']), str(SOURCE))
    queue = Path('encoder/kwt_joint_output_queue.sv')
    (SOURCE / queue).write_text(ring((ROOT / cfg['source_snapshot'] / queue).read_text(), direct),
                               newline='\n')
    SOC.mkdir(exist_ok=True)
    old = SOC.with_name(PARENT)
    for path in old.iterdir():
        if not path.is_file() or path.suffix not in ('.sv', '.v', '.svh', '.f', '.json', '.sh'):
            continue
        content = path.read_text().replace(PARENT, NAME)
        if path.name == 'complete_soc_tb.sv':
            content = native_observer(content, direct)
        (SOC / path.name).write_text(content, newline='\n')
    eda = SOC / 'eda'
    eda.mkdir(exist_ok=True)
    for path in (old / 'eda').glob('*.tcl'):
        (eda / path.name).write_text(path.read_text().replace(PARENT, NAME), newline='\n')
    shutil.copytree(old / 'packed_inputs', SOC / 'packed_inputs', dirs_exist_ok=True)
    manifest = json.loads((ROOT / cfg['adaptive_manifest']).read_text())
    manifest.update(variant=NAME, parent_variant=PARENT, purpose='experiment', retirement=winner)
    manifest['parent'] = dict(variant=PARENT, configuration=cfg, firmware=cfg['firmware'],
                              source_snapshot=cfg['source_snapshot'], profile=cfg['implementation'])
    manifest['hardware'] += ['R4'] + (['F2'] if direct else [])
    profile = ROOT / 'constraints' / NAME / 'candidates'
    profile.mkdir(parents=True, exist_ok=True)
    (profile / (NAME + '.json')).write_text(json.dumps(manifest, indent=2) + '\n')
    RTL_TEST.mkdir(exist_ok=True)
    shutil.copyfile(RTL_TEST.with_name(PARENT) / 'loading_dma_tb.sv', RTL_TEST / 'loading_dma_tb.sv')


def develop():
    stream.SOURCE, stream.RTL_TEST, stream.REPORT = SOURCE, RTL_TEST, REPORT
    stream.develop()


if __name__ == '__main__':
    {'materialize': materialize, 'develop': develop}[sys.argv[1]]()
