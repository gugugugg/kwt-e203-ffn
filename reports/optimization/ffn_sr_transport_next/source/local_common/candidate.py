"""Materialize only the DMA variant selected by the four cold-task models."""
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_sr_transport_next'
NAME = 'ffn_sr_bidir'
PARENT = 'ffn_ara_SR'
OUT = ROOT / 'build/optimization/complete_soc' / NAME
OLD = OUT.with_name(PARENT)
ENDPOINT = 'kwt_shared_dma_icb_sm40.sv'
PRIVATE = Path('encoder/kwt_ld_engine.sv')
PROFILES = ROOT / 'constraints' / NAME
sys.path.insert(0, str(ROOT/'scripts/sr_pr1'))
from prepare import replace, transform as pr1_endpoint


def dump(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + '\n')


def endpoint(text, winner):
    text = pr1_endpoint(text)
    read_fast = "(joined_cmd_read&&(joined_cmd_addr>=32'ha0020000)&&(joined_cmd_addr<32'ha0028800))"
    write_fast = "(!joined_cmd_read&&(joined_cmd_addr>=32'ha0010000)&&(joined_cmd_addr<32'ha001c600))"
    modes = []
    if 'PRF' in winner:
        modes.append(read_fast)
    if 'W1' in winner:
        modes.append(write_fast)
    text = replace(text, """    wire next_fast_read=joined_cmd_dma&&joined_cmd_read&&(joined_cmd_addr[1:0]==2'b00)&&
                        (joined_cmd_addr>=32'ha0020000)&&(joined_cmd_addr<32'ha0028800);""",
        "    wire next_fast_read=joined_cmd_dma&&(joined_cmd_addr[1:0]==2'b00)&&\n"
        "                        ("+"||\n                         ".join(modes)+");")
    text = replace(text, 'early_response?memory_rdata:stored_rsp_rdata',
                         "early_response?(read_pending?memory_rdata:32'b0):stored_rsp_rdata")
    # The synchronous endpoint has no response before an owner is registered.
    # Full-credit command eligibility must not feed back into its own response.
    text = replace(text, """    wire recipient=active?owner:grant;
    assign s_rsp_ready=recipient?b_rsp_ready:a_rsp_ready;""",
        """    assign s_rsp_ready=active&&(owner?b_rsp_ready:a_rsp_ready);""")
    text = replace(text, """    assign a_rsp_valid=s_rsp_valid&&(active||fire)&&!recipient;
    assign b_rsp_valid=s_rsp_valid&&(active||fire)&&recipient;""",
        """    assign a_rsp_valid=s_rsp_valid&&active&&!owner;
    assign b_rsp_valid=s_rsp_valid&&active&&owner;""")
    text = replace(text, 'active<=active||!(s_rsp_valid&&s_rsp_ready);', "active<=1'b1;")
    return text.replace('pending_fast_read', 'pending_fast_access').replace('next_fast_read', 'next_fast_access')


def engine(text, winner):
    if 'PRF' in winner:
        text = replace(text, "        (pd_count<2);\n    wire pio_source_valid",
            """        ((pd_count<2)||
         (pd_count==2&&address>=32'ha0020000&&address<32'ha0028800&&
          address[1:0]==2'b00&&pio_dest_complete&&!pio_rsp_err));
    wire pio_source_valid""")
    if 'W1' in winner:
        text = replace(text, "        !pd_source_pending&&(pd_count<2)&&output_ready;",
            """        !pd_source_pending&&output_ready&&
        ((pd_count<2)||
         (pd_count==2&&pd_dest_pending&&mem_rsp_valid&&!mem_rsp_err&&
          address>=32'ha0010004&&address<=32'ha001c600&&address[1:0]==2'b00));""")
    return text


def observe_handoffs(text):
    return replace(text,
        "if(!dut.shared_memory.memory_arbiter.owner||dut.shared_memory.pending||",
        """if(!dut.shared_memory.memory_arbiter.owner||
           (dut.shared_memory.pending&&
            !(dut.shared_memory.early_response&&dut.shared_memory.next_fast_access))||""")


def mapped_core(source):
    """Carry the actual accepted SR arithmetic through DC with its original hierarchy."""
    modules = {m[1]: m[0] for m in re.finditer(r'(?ms)^module (\w+)\s.*?^endmodule\b', source)}
    instantiate = re.compile(r'(?m)^([ \t]+)(\w+)(?= +\S+ +\()')
    used = {'kwt_encoder'}
    pending = ['kwt_encoder']
    while pending:
        part = pending.pop()
        for match in instantiate.finditer(modules[part]):
            name = match[2]
            if name in modules and name not in used:
                used.add(name)
                pending.append(name)
    renamed = {name: 'sr_phys_'+name for name in used if name != 'kwt_encoder'}
    core = modules['kwt_encoder']
    core = replace(core, 'module kwt_encoder (', """module kwt_encoder #(
    parameter integer SPLIT_BIAS=1, FAST_PAIR=1, OVERLAP=0, LANES=16, CLOCK_GATING=1
) (""")
    ports = re.search(r'trace_high, out_index_14_,.*?\);', core, re.S)[0]
    core = replace(core, ports, 'trace_high, out_index );')
    declaration = re.search(r'out_pair_valid, trace_valid, trace_pair_valid, out_index_14_,.*?;', core, re.S)[0]
    signals = ['out_index_%d_' % i if i != 8 else 'out_index_8__BAR' for i in range(14, -1, -1)]
    core = replace(core, declaration, 'out_pair_valid, trace_valid, trace_pair_valid;\n'
        '  output [14:0] out_index;\n  wire '+', '.join(signals)+';')
    values = ['transport_index8_positive' if signal.endswith('_BAR') else signal for signal in signals]
    core = core.replace('endmodule',
        '  wire transport_index8_positive;\n'
        '  CLKINV2_12TR40 I_0 (.I(out_index_8__BAR), .ZN(transport_index8_positive));\n'
        '  assign out_index = {'+', '.join(values)+'};\nendmodule', 1)
    modules['kwt_encoder'] = core
    results = []
    for name in sorted(used):
        block = instantiate.sub(lambda m: m[1]+renamed.get(m[2],m[2]), modules[name])
        if name in renamed:
            block = block.replace('module '+name+' ', 'module '+renamed[name]+' ', 1)
        results.append(block)
    return '\n\n'.join(results)+'\n', sorted(used)


def materialize(winner):
    selection = ROOT/'constraints/ffn_selected.json'
    cfg = json.loads(selection.read_text())
    if cfg['variant'] != PARENT or winner not in ('PRF','W1','PRF_W1'):
        raise RuntimeError('Expected published SR and one selected transport model')
    selected = REPORT/'baseline-selected.json'
    if selected.exists() and selected.read_bytes() != selection.read_bytes():
        raise RuntimeError('Frozen SR baseline differs')
    if not selected.exists():
        shutil.copyfile(str(selection), str(selected))
    source = ROOT/cfg['source_snapshot']
    candidate = ROOT/'build/optimization/rtl_sources'/NAME
    if not candidate.exists():
        shutil.copytree(str(source),str(candidate))
    new_engine = engine((source/PRIVATE).read_text(),winner)
    new_endpoint = endpoint((OLD/ENDPOINT).read_text(),winner)
    (candidate/PRIVATE).write_bytes(new_engine.encode('ascii'))
    (REPORT/PRIVATE.name).write_bytes(new_engine.encode('ascii'))
    (REPORT/ENDPOINT).write_bytes(new_endpoint.encode('ascii'))
    OUT.mkdir(parents=True,exist_ok=True)
    for path in OLD.iterdir():
        if not path.is_file() or path.name == 'gate_tb.sv' or path.suffix not in ('.sv','.svh','.v','.f','.json'):
            continue
        data = path.read_bytes()
        if path.name == ENDPOINT:
            data = new_endpoint.encode('ascii')
        elif path.suffix in ('.f','.json') or path.name == 'complete_soc_tb.sv':
            data = data.replace(PARENT.encode(),NAME.encode())
            data = data.replace(('build/optimization/firmware/'+NAME).encode(),
                                ('build/optimization/firmware/'+PARENT).encode())
            data = data.replace(('constraints/ffn_ar_area/candidates/'+NAME).encode(),
                                ('constraints/'+NAME+'/candidates/'+NAME).encode())
            if path.name == 'complete_soc_tb.sv':
                data = observe_handoffs(data.decode('ascii')).encode('ascii')
        (OUT/path.name).write_bytes(data)
    manifest = json.loads((ROOT/cfg['adaptive_manifest']).read_text())
    manifest.update(variant=NAME,parent_variant=PARENT,parent=dict(variant=PARENT,
        firmware=cfg['firmware'],source_snapshot=cfg['source_snapshot'],configuration=cfg,
        profile=cfg['implementation']),hardware=manifest['hardware']+[winner],purpose='experiment')
    dump(PROFILES/'candidates'/(NAME+'.json'),manifest)
    eda = OUT/'eda'
    eda.mkdir(exist_ok=True)
    for path in (OLD/'eda').glob('*.tcl'):
        data = path.read_bytes().replace(PARENT.encode(),NAME.encode())
        if path.name=='power.tcl':
            data = data.replace(b'reports/optimization/ffn_ar_area/activity-mapping/',
                                b'reports/optimization/ffn_sr_transport_next/activity-mapping/')
        (eda/path.name).write_bytes(data)
    return cfg


def prepare_frozen_core(cfg):
    sr_final = ROOT/'build/server'/('complete_soc_sm40_'+cfg['implementation']['tag'])/'netlist.v'
    text, modules = mapped_core(sr_final.read_text())
    core = OUT/'preserved_sr_core.v'
    core.write_bytes(text.encode('ascii'))
    sources = (OUT/'synthesis_files.f').read_text()
    rtl = 'build/optimization/rtl_sources/'+NAME+'/encoder/kwt_encoder.sv'
    (OUT/'mapping_files.f').write_text(replace(sources,rtl,core.relative_to(ROOT).as_posix()))
    template = OUT/'eda/synthesize.tcl'
    source = replace(template.read_text(),'/synthesis_files.f r]', '/mapping_files.f r]')
    insertion = """set frozen_core [get_cells soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/controller/core]
set_dont_touch $frozen_core
puts "XPIAN_SR_CORE_FROZEN=[get_object_name $frozen_core]"
"""
    (OUT/'eda/synthesize_frozen_core.tcl').write_text(replace(source,
        'source constraints/complete_soc.sdc',insertion+'source constraints/complete_soc.sdc'))
    dump(REPORT/'preserved-core.json',dict(source=sr_final.relative_to(ROOT).as_posix(),
         modules=modules,boundary='kwt_encoder',adapter='out_index scalarization and bit8 inverse',
         reference_file_list='synthesis_files.f',mapping_file_list='mapping_files.f'))


if __name__ == '__main__':
    result=json.loads((REPORT/'model-results.json').read_text())
    winner=result['winner']
    cfg=materialize(winner)
    prepare_frozen_core(cfg)
    dump(REPORT/'model-selection.json',dict(winner=winner,cycles_total=result['cycles_total']))
