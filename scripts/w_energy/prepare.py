"""Materialize independent C/SL core edits on the frozen published W."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];BUILD=ROOT/'build/optimization/ffn_w_energy';REPORT=ROOT/'reports/optimization/ffn_w_energy'

def variants():
    p=REPORT/'models/selection.json'
    return ['ffn_wen_'+x for x in json.loads(p.read_text())['candidates']] if p.exists() else ['ffn_wen_SL']

def control_transform(text):
    changes=[('    wire ap_er_reseed=jp_quant_commit&&ap_er_has_next;',
        '    wire ap_er_reseed=jp_quant_commit&&ap_er_has_next;\n    wire wen_tile_handoff=jp_quant_commit&&jp_last_emit_row&&lane==14&&tile<15;'),
        ('if(ap_er_seed_wait)ap_er_next_seed_ready<=0;\n            if(ap_er_reseed&&jp_last_emit_row&&lane==14)ap_er_next_seed_ready<=1;',
        'if(ap_er_seed_wait||wen_tile_handoff)ap_er_next_seed_ready<=0;\n            else if(ap_er_reseed&&jp_last_emit_row&&lane==14)ap_er_next_seed_ready<=1;'),
        ("else if(tile<15)begin tile<=tile+1'b1;state<=MAC_INIT;end","else if(tile<15)begin tile<=tile+1'b1;inner<=0;chunk<=0;state<=A_REQ;end")]
    for old,new in changes:
        if text.count(old)!=1:raise RuntimeError('Read the frozen W control expression')
        text=text.replace(old,new,1)
    return text

def write_transform(text):
    old='read_handoff_allowed&&active&&owner&&owner_read&&\n        grant&&b_cmd_valid&&b_cmd_read;'
    new='read_handoff_allowed&&active&&owner&&\n        grant&&b_cmd_valid&&(owner_read==b_cmd_read);'
    if text.count(old)!=1:raise RuntimeError('Read the original shared read handoff')
    return text.replace(old,new,1)

def prepare(name):
    if name not in variants():raise ValueError('Unselected W-energy variant '+name)
    kind=name[len('ffn_wen_'):];parent=json.loads((BUILD/'frozen/parent.json').read_text());source=BUILD/'frozen/rtl_sources';target=ROOT/'build/optimization/rtl_sources'/name
    changes=[]
    for p in source.rglob('*'):
        if not p.is_file():continue
        value=p.read_bytes()
        if p.name=='kwt_encoder.sv':
            text=value.decode()
            if kind=='C':text=control_transform(text)
            else:
                old='always_latch if(!clk)jp_shift_return=shift_rdata;'
                if text.count(old)!=1:raise RuntimeError('Read the frozen W LOW shift-return latch')
                text=text.replace(old,'always_latch if(!shift_clk)jp_shift_return=shift_rdata;',1)
            value=text.encode();changes.append(dict(path=p.relative_to(source).as_posix(),mechanism=kind))
        t=target/p.relative_to(source);t.parent.mkdir(parents=True,exist_ok=True)
        if not t.exists() or t.read_bytes()!=value:t.write_bytes(value)
    manifest={k:v for k,v in parent.items() if k not in ['state','profile','firmware','source_snapshot','configuration','program']}
    manifest.update(variant=name,parent_variant='ffn_ce_W',parent=parent,hardware=list(parent['hardware'])+[kind],
        w_energy_hardware=[kind],effective_changes=dict(parent['effective_changes'],w_energy_hardware=[kind]),purpose='experiment',
        objective=['energy_below_W','area_within_authorized_budget','throughput_at_least_1000'],automatic_release_switch=False)
    d=ROOT/'constraints/ffn_w_energy/candidates';d.mkdir(parents=True,exist_ok=True);(d/(name+'.json')).write_text(json.dumps(manifest,indent=2))
    (REPORT/(name+'-source-changes.json')).write_text(json.dumps(dict(parent='ffn_ce_W',changes=changes,other_files_byte_equal=True,combined=False),indent=2))
    return manifest,target

if __name__=='__main__':
    for name in variants():prepare(name)
