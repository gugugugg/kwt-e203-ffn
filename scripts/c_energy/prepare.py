"""Derive only selected independent mechanisms from the frozen published C."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];BUILD=ROOT/'build/optimization/ffn_c_energy';REPORT=ROOT/'reports/optimization/ffn_c_energy'
def variants():return ['ffn_cen_'+name for name in json.loads((REPORT/'models/selection.json').read_text())['candidates']]
def prepare(name):
    if name not in variants():raise ValueError('Unselected C-energy candidate '+name)
    kind=name[len('ffn_cen_'):];parent=json.loads((BUILD/'frozen/parent.json').read_text());source=BUILD/'frozen/rtl_sources';target=ROOT/'build/optimization/rtl_sources'/name;changes=[]
    for p in source.rglob('*'):
        if not p.is_file():continue
        value=p.read_bytes()
        if p.name=='kwt_encoder.sv':
            text=value.decode()
            if kind=='SL':
                old='always_latch if(!clk)jp_shift_return=shift_rdata;'
                if text.count(old)!=1:raise RuntimeError('Read frozen C shift LOW latch')
                text=text.replace(old,'always_latch if(!shift_clk)jp_shift_return=shift_rdata;',1)
            else:raise ValueError('XR had no final-commit improvement and has no generated hardware')
            value=text.encode();changes.append(dict(path=p.relative_to(source).as_posix(),mechanism=kind))
        t=target/p.relative_to(source);t.parent.mkdir(parents=True,exist_ok=True)
        if not t.exists() or t.read_bytes()!=value:t.write_bytes(value)
    manifest={k:v for k,v in parent.items() if k not in ['state','profile','firmware','source_snapshot','configuration','program']}
    manifest.update(variant=name,parent_variant='ffn_wen_C',parent=parent,hardware=list(parent['hardware'])+[kind],c_energy_hardware=[kind],effective_changes=dict(parent['effective_changes'],c_energy_hardware=[kind]),purpose='experiment',objective=['energy_below_C','area_within_authorized_budget','throughput_at_least_1000'],automatic_release_switch=False)
    d=ROOT/'constraints/ffn_c_energy/candidates';d.mkdir(parents=True,exist_ok=True);(d/(name+'.json')).write_text(json.dumps(manifest,indent=2));(REPORT/(name+'-source-changes.json')).write_text(json.dumps(dict(parent='ffn_wen_C',changes=changes,other_files_byte_equal=True,combined=False),indent=2));return manifest,target
if __name__=='__main__':
    for name in variants():prepare(name)
