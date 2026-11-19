"""Derive only AR and D1 independently from the frozen published C bytes."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];BUILD=ROOT/'build/optimization/ffn_c_area';REPORT=ROOT/'reports/optimization/ffn_c_area'

def variants():return ['ffn_car_AR','ffn_car_D1']

def accumulator_no_reset(text):
    old='''        always @(posedge accumulator_clk or negedge rst_n)begin
            if(!rst_n)accumulator[jp_lane]<=0;
            else if(seed_update)accumulator[jp_lane]<=36'($signed(bias_pair[(jp_column%2)*64+:64]));
            else if(mac_update)accumulator[jp_lane]<=accumulator[jp_lane]+36'(activation*weight_value);
        end
'''
    new='''        always @(posedge accumulator_clk)begin
            if(seed_update)accumulator[jp_lane]<=36'($signed(bias_pair[(jp_column%2)*64+:64]));
            else if(mac_update)accumulator[jp_lane]<=accumulator[jp_lane]+36'(activation*weight_value);
        end
'''
    if text.count(old)!=1:raise RuntimeError('Read the frozen C accumulator block')
    return text.replace(old,new,1)

def redundant_destination_count(text):
    text=text.replace('reg [31:0] address,source_remaining,dest_remaining;','reg [31:0] address,source_remaining;')
    text=text.replace('source_remaining<=0;dest_remaining<=0;','source_remaining<=0;')
    text=text.replace('source_remaining<=word_count;dest_remaining<=word_count;','source_remaining<=word_count;')
    text=text.replace('                dest_remaining<=dest_remaining-1;\n','')
    text=text.replace('if(dest_remaining==1)begin','if(source_remaining==0&&pd_count==1)begin')
    if 'dest_remaining' in text:raise RuntimeError('Read remaining destination state references')
    return text

def prepare(name):
    if name not in variants():raise ValueError('Unapproved C area candidate '+name)
    library=json.loads((REPORT/'library/acceptance.json').read_text())
    if not library['passed']:raise RuntimeError('Read the finite same-library inspection before RTL materialization')
    kind=name[len('ffn_car_'):];parent=json.loads((BUILD/'frozen/parent.json').read_text());source=BUILD/'frozen/rtl_sources';target=ROOT/'build/optimization/rtl_sources'/name;changes=[]
    for p in source.rglob('*'):
        if not p.is_file():continue
        value=p.read_bytes()
        if kind=='AR' and p.name=='kwt_encoder.sv':value=accumulator_no_reset(value.decode()).encode()
        elif kind=='D1' and p.name=='kwt_ld_engine.sv':value=redundant_destination_count(value.decode()).encode()
        if value!=p.read_bytes():changes.append(dict(path=p.relative_to(source).as_posix(),mechanism=kind))
        t=target/p.relative_to(source);t.parent.mkdir(parents=True,exist_ok=True)
        if not t.exists() or t.read_bytes()!=value:t.write_bytes(value)
    assert len(changes)==1
    manifest={k:v for k,v in parent.items() if k not in ['state','profile','firmware','source_snapshot','configuration','program']}
    manifest.update(variant=name,parent_variant='ffn_wen_C',parent=parent,hardware=list(parent['hardware'])+[kind],c_area_hardware=[kind],effective_changes=dict(parent['effective_changes'],c_area_hardware=[kind]),purpose='experiment',objective=['area_below_C','throughput_at_least_1000','prefer_energy_not_increased_keep_tradeoffs'],automatic_release_switch=False)
    d=ROOT/'constraints/ffn_c_area/candidates';d.mkdir(parents=True,exist_ok=True);(d/(name+'.json')).write_text(json.dumps(manifest,indent=2));REPORT.mkdir(parents=True,exist_ok=True);(REPORT/(name+'-source-changes.json')).write_text(json.dumps(dict(parent='ffn_wen_C',changes=changes,other_files_byte_equal=True,combined=False),indent=2));return manifest,target

if __name__=='__main__':
    for name in variants():prepare(name)
