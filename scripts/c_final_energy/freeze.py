"""Freeze published C and the previous objective before this independent experiment."""
from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parents[2];BUILD=ROOT/'build/optimization/ffn_c_final_energy';REPORT=ROOT/'reports/optimization/ffn_c_final_energy'

def main():
    frozen=BUILD/'frozen';frozen.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    selected=json.loads((ROOT/'constraints/ffn_selected.json').read_text())
    if selected['variant']!='ffn_wen_C':raise RuntimeError('Read published C')
    if not (frozen/'parent.json').exists():
        manifest=json.loads((ROOT/selected['adaptive_manifest']).read_text());(frozen/'parent-manifest-original.json').write_text(json.dumps(manifest,indent=2));manifest.pop('parent',None)
        manifest.update(state=selected['measured'],profile=selected['implementation'],configuration=selected,firmware='build/optimization/ffn_c_final_energy/frozen/firmware',source_snapshot='build/optimization/ffn_c_final_energy/frozen/rtl_sources',program='build/optimization/ffn_c_final_energy/frozen/program')
        (frozen/'parent.json').write_text(json.dumps(manifest,indent=2))
        for source,target in [(selected['source_snapshot'],'rtl_sources'),(selected['firmware'],'firmware'),(selected['linear_images'],'images'),('build/optimization/ffn_w_energy/frozen/program','program')]:shutil.copytree(str(ROOT/source),str(frozen/target))
        for source,target in [('constraints/ffn_selected.json','selected-original.json'),('constraints/ffn_next_objective.json','previous-objective.json'),('constraints/ffn_submission_priority.json','previous-priority.json'),('AGENTS.md','AGENTS-before.md')]:shutil.copyfile(str(ROOT/source),str(frozen/target))
    objective=json.loads((frozen/'previous-objective.json').read_text())
    objective.update(status='implementation_authorized',active_experiment='ffn_c_final_energy',automatic_release_switch=False,user_request='Fixed SS; one O1 causal model, generate O1 after own12 correctness/T and N>0 or aggregate commit improvement; independent candidates')
    objective['joint_target'].update(mean_task_energy_j_strictly_below=1.8076843983968133e-05,scoring_area_mm2_at_most=.2764843225,throughput_tasks_per_second_at_least=1000,cycle_weighted_mean_power_w_at_most=None,mean_power_may_increase=True)
    for p in [ROOT/'constraints/ffn_next_objective.json',REPORT/'objective.json']:p.write_text(json.dumps(objective,indent=2))
    note='- Latest implementation authorization 2026-11-05: ffn_c_final_energy; fixed SS shared shift state, conditional O1 FIFO-head bypass after one causal12 model. Independent from published C; no combination, third candidate, SL/XR retries or scans. E<1.8076843983968133e-05J, A<=.2764843225mm2, T>=1000; mean P may rise. Primary personally implements/reviews/accepts/synchronizes E/G/native ACK. C and W/C16/IR rollback unchanged. No qualifying E result leads only to area planning, not automatic area implementation.\n\n'
    p=ROOT/'AGENTS.md';text=p.read_text(encoding='utf8')
    if note not in text:p.write_text(text.replace('# Project workspace\n\n','# Project workspace\n\n'+note,1),encoding='utf8')
    print('C_FINAL_ENERGY_FROZEN_C',flush=True)

if __name__=='__main__':main()
