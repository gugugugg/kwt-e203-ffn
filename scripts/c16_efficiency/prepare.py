"""Materialize only the model-selected efficiency child of frozen C16."""
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BUILD=ROOT/'build/optimization/ffn_c16_efficiency'
REPORT=ROOT/'reports/optimization/ffn_c16_efficiency'


def selection():
    return json.loads((REPORT/'models/selection.json').read_text())['selected']


def control_transform(text):
    text=text.replace('    wire ap_er_reseed=jp_quant_commit&&ap_er_has_next;',
        '    wire ap_er_reseed=jp_quant_commit&&ap_er_has_next;\n'
        '    wire ce_tile_handoff=jp_quant_commit&&jp_last_emit_row&&lane==14&&tile<15;')
    text=text.replace('if(ap_er_seed_wait)ap_er_next_seed_ready<=0;\n            if(ap_er_reseed&&jp_last_emit_row&&lane==14)ap_er_next_seed_ready<=1;',
        'if(ap_er_seed_wait||ce_tile_handoff)ap_er_next_seed_ready<=0;\n'
        '            else if(ap_er_reseed&&jp_last_emit_row&&lane==14)ap_er_next_seed_ready<=1;')
    text=text.replace("else if(tile<15)begin tile<=tile+1'b1;state<=MAC_INIT;end",
        "else if(tile<15)begin tile<=tile+1'b1;inner<=0;chunk<=0;state<=A_REQ;end")
    return text


def write_transform(text):
    old='read_handoff_allowed&&active&&owner&&owner_read&&\n        grant&&b_cmd_valid&&b_cmd_read;'
    new='read_handoff_allowed&&active&&owner&&\n        grant&&b_cmd_valid&&(owner_read==b_cmd_read);'
    if old not in text:raise ValueError('Inspect the frozen same-DMA read handoff expression')
    return text.replace(old,new,1)


def prepare():
    chosen=selection()
    if chosen is None:raise ValueError('Both models have no net benefit; no hardware authorized')
    name='ffn_ce_'+chosen
    parent=json.loads((BUILD/'frozen/parent.json').read_text())
    target=ROOT/'build/optimization/rtl_sources'/name
    for path in (BUILD/'frozen/rtl_sources').rglob('*'):
        if path.is_file():
            dest=target/path.relative_to(BUILD/'frozen/rtl_sources')
            dest.parent.mkdir(parents=True,exist_ok=True)
            value=path.read_bytes()
            if chosen=='C' and path.name=='kwt_encoder.sv':
                value=control_transform(value.decode()).encode()
            if not dest.exists() or dest.read_bytes()!=value:dest.write_bytes(value)
    manifest=dict(parent)
    for key in ['state','profile','firmware','source_snapshot','configuration','program']:manifest.pop(key,None)
    manifest.update(variant=name,parent_variant='ffn_cp_C16',parent=parent,
        hardware=list(parent['hardware'])+[chosen],c16_efficiency_hardware=[chosen],
        effective_changes=dict(parent['effective_changes'],c16_efficiency_hardware=[chosen]),
        objective=['energy_below_C16','area_within_authorized_budget','throughput_at_least_1000'],
        purpose='experiment',automatic_release_switch=False)
    folder=ROOT/'constraints/ffn_c16_efficiency/candidates';folder.mkdir(parents=True,exist_ok=True)
    (folder/(name+'.json')).write_text(json.dumps(manifest,indent=2))
    (REPORT/'candidate.json').write_text(json.dumps(manifest,indent=2))
    return manifest,target


NAME='ffn_ce_'+selection() if selection() is not None else None

if __name__=='__main__':prepare()
