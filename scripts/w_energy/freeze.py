"""Freeze the published W inputs for the two explicitly authorized independent changes."""
from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parents[2]
BUILD=ROOT/'build/optimization/ffn_w_energy';REPORT=ROOT/'reports/optimization/ffn_w_energy'

def main():
    frozen=BUILD/'frozen';frozen.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    selected=json.loads((ROOT/'constraints/ffn_selected.json').read_text())
    if selected['variant']!='ffn_ce_W':raise RuntimeError('Read the current published W')
    if not (frozen/'parent.json').exists():
        manifest=json.loads((ROOT/'constraints/ffn_c16_efficiency/candidates/ffn_ce_W.json').read_text())
        (frozen/'parent-manifest-original.json').write_text(json.dumps(manifest,indent=2))
        manifest.pop('parent',None)
        manifest.update(state=selected['measured'],profile=selected['implementation'],configuration=selected,
            firmware='build/optimization/ffn_w_energy/frozen/firmware',source_snapshot='build/optimization/ffn_w_energy/frozen/rtl_sources',
            program='build/optimization/ffn_w_energy/frozen/program')
        (frozen/'parent.json').write_text(json.dumps(manifest,indent=2))
        for source,target in [(selected['source_snapshot'],'rtl_sources'),(selected['firmware'],'firmware'),
            ('build/optimization/ffn_c16_efficiency/frozen/images','images'),('build/optimization/ffn_c16_efficiency/frozen/program','program')]:
            shutil.copytree(str(ROOT/source),str(frozen/target))
        for source,target in [('constraints/ffn_selected.json','selected-original.json'),('constraints/ffn_next_objective.json','previous-objective.json'),('AGENTS.md','AGENTS-before.md')]:shutil.copyfile(str(ROOT/source),str(frozen/target))
    objective=json.loads((frozen/'previous-objective.json').read_text())
    objective.update(status='implementation_authorized',active_experiment='ffn_w_energy',automatic_release_switch=False,
        user_request='Independent C-on-W after model screening, and shift-return LOW latch clock reuse; no combination')
    objective['fixed_reference']=dict(variant='ffn_ce_W',cycles=99016,mean_energy_j=1.822518977709749e-05,mean_power_w=.027609461769457697,
        scoring_area_mm2=.252858163,source='reports/optimization/ffn_c16_efficiency/final-selection.json')
    objective['joint_target'].update(reference_variant='ffn_ce_W',mean_task_energy_j_strictly_below=1.822518977709749e-05,
        scoring_area_mm2_at_most=.2764843225,throughput_tasks_per_second_at_least=1000,cycle_weighted_mean_power_w_at_most=None,
        release='Published W retained; C16/IR rollback; no automatic switch')
    for p in [ROOT/'constraints/ffn_next_objective.json',REPORT/'objective.json']:p.write_text(json.dumps(objective,indent=2))
    agents=ROOT/'AGENTS.md';text=agents.read_text(encoding='utf-8')
    note='- Latest implementation authorization 2026-11-04: ffn_w_energy, at most independent ffn_wen_C (only if own W model reduces total final-commit cycles) and ffn_wen_SL (LOW shift return uses existing shift_clk). No combination, ACK credit, output bypass, shift sharing, new MAC/SRAM or scans. E<1.822518977709749e-05J, A<=0.2764843225mm2, T>=1000; average power may rise. Primary personally implements, validates and synchronizes E/G/native ACK; published W and C16/IR rollback stay unchanged.\n\n'
    if note not in text:agents.write_text(text.replace('# Project workspace\n\n','# Project workspace\n\n'+note,1),encoding='utf-8')
    print('W_ENERGY_FROZEN',flush=True)

if __name__=='__main__':main()
