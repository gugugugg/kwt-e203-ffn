"""Freeze the published C and retain the completed round's objective bytes."""
from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parents[2];BUILD=ROOT/'build/optimization/ffn_c_energy';REPORT=ROOT/'reports/optimization/ffn_c_energy'
def main():
    frozen=BUILD/'frozen';frozen.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    selected=json.loads((ROOT/'constraints/ffn_selected.json').read_text())
    if selected['variant']!='ffn_wen_C':raise RuntimeError('Read published C')
    if not (frozen/'parent.json').exists():
        manifest=json.loads((ROOT/selected['adaptive_manifest']).read_text());(frozen/'parent-manifest-original.json').write_text(json.dumps(manifest,indent=2));manifest.pop('parent',None)
        manifest.update(state=selected['measured'],profile=selected['implementation'],configuration=selected,firmware='build/optimization/ffn_c_energy/frozen/firmware',source_snapshot='build/optimization/ffn_c_energy/frozen/rtl_sources',program='build/optimization/ffn_c_energy/frozen/program')
        (frozen/'parent.json').write_text(json.dumps(manifest,indent=2))
        for source,target in [(selected['source_snapshot'],'rtl_sources'),(selected['firmware'],'firmware'),(selected['linear_images'],'images'),('build/optimization/ffn_w_energy/frozen/program','program')]:shutil.copytree(str(ROOT/source),str(frozen/target))
        for source,target in [('constraints/ffn_selected.json','selected-original.json'),('constraints/ffn_next_objective.json','previous-objective.json'),('constraints/ffn_submission_priority.json','previous-priority.json'),('AGENTS.md','AGENTS-before.md')]:shutil.copyfile(str(ROOT/source),str(frozen/target))
    objective=json.loads((frozen/'previous-objective.json').read_text());objective.update(status='implementation_authorized',active_experiment='ffn_c_energy',automatic_release_switch=False,user_request='SL on published C; one XR model, generate XR only after net final-commit reduction; independent candidates')
    objective['fixed_reference']=dict(variant='ffn_wen_C',cycles=98783,mean_energy_j=1.8076843983968133e-05,mean_power_w=.027449324252100258,scoring_area_mm2=.252275623,source='reports/submission/wen-C-release-20261104/completion.json')
    objective['joint_target'].update(reference_variant='ffn_wen_C',mean_task_energy_j_strictly_below=1.8076843983968133e-05,scoring_area_mm2_at_most=.2764843225,throughput_tasks_per_second_at_least=1000,cycle_weighted_mean_power_w_at_most=None,release='Published C retained; W/C16/IR rollback; no automatic switch')
    objective['selection_order']=['Full same-precision platform acceptance','E<C, A<=.2764843225, T>=1000','E ascending, T descending, A ascending']
    for p in [ROOT/'constraints/ffn_next_objective.json',REPORT/'objective.json']:p.write_text(json.dumps(objective,indent=2))
    note='- Latest implementation authorization 2026-11-04: ffn_c_energy, fixed ffn_cen_SL on published C plus ffn_cen_XR only if its sole causal model reduces aggregate12 final-commit cycles. No combination, ACK credit, row0 bypass, extra MAC/SRAM or scans. E<1.8076843983968133e-05J, A<=.2764843225mm2, T>=1000; mean power may rise. Primary personally implements/reviews/accepts/synchronizes E/G/native ACK. Published C and W/C16/IR rollback remain unchanged.\n\n'
    p=ROOT/'AGENTS.md';text=p.read_text(encoding='utf8')
    if note not in text:p.write_text(text.replace('# Project workspace\n\n','# Project workspace\n\n'+note,1),encoding='utf8')
    print('C_ENERGY_FROZEN_PUBLISHED_C',flush=True)
if __name__=='__main__':main()
