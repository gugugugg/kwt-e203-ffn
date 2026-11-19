"""Freeze published C and the previous objective before this independent experiment."""
from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parents[2];BUILD=ROOT/'build/optimization/ffn_c_area';REPORT=ROOT/'reports/optimization/ffn_c_area'

def main():
    frozen=BUILD/'frozen';frozen.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    selected=json.loads((ROOT/'constraints/ffn_selected.json').read_text())
    if selected['variant']!='ffn_wen_C':raise RuntimeError('Read published C')
    if not (frozen/'parent.json').exists():
        manifest=json.loads((ROOT/selected['adaptive_manifest']).read_text());(frozen/'parent-manifest-original.json').write_text(json.dumps(manifest,indent=2));manifest.pop('parent',None)
        manifest.update(state=selected['measured'],profile=selected['implementation'],configuration=selected,firmware='build/optimization/ffn_c_area/frozen/firmware',source_snapshot='build/optimization/ffn_c_area/frozen/rtl_sources',program='build/optimization/ffn_c_area/frozen/program')
        (frozen/'parent.json').write_text(json.dumps(manifest,indent=2))
        for source,target in [(selected['source_snapshot'],'rtl_sources'),(selected['firmware'],'firmware'),(selected['linear_images'],'images'),('build/optimization/ffn_w_energy/frozen/program','program')]:shutil.copytree(str(ROOT/source),str(frozen/target))
        for source,target in [('constraints/ffn_selected.json','selected-original.json'),('constraints/ffn_next_objective.json','previous-objective.json'),('constraints/ffn_submission_priority.json','previous-priority.json'),('AGENTS.md','AGENTS-before.md')]:shutil.copyfile(str(ROOT/source),str(frozen/target))
    objective=json.loads((frozen/'previous-objective.json').read_text())
    objective.update(status='implementation_authorized',updated_at='2026-11-05',active_experiment='ffn_c_area',automatic_release_switch=False,user_request='Fixed independent AR and D1 from published C; retain32MAC/SRAM; lower scoring area, prefer nonincreased task energy and retain measured Pareto tradeoffs without percentage threshold',no_new_experiments_started=False)
    objective['joint_target'].pop('scoring_area_mm2_at_most',None)
    objective['joint_target'].update(mean_task_energy_j_strictly_below=None,preferred_mean_task_energy_j_at_most=1.8076843983968133e-05,energy_increase_is_hard_failure=False,scoring_area_mm2_strictly_below=.252275623,throughput_tasks_per_second_at_least=1000,cycle_weighted_mean_power_w_at_most=None,mean_power_may_increase=True)
    objective.update(selection_order=['same_numerical_model_and_full_acceptance','throughput_at_least1000','area_strictly_below_C','prefer_E_not_above_C','Pareto_and_official_score_break_even_no_invented_opponent_data'],planning_sequence='implemented by primary only; no agent implementation',subagents='planning completed; no agents for implementation')
    for p in [ROOT/'constraints/ffn_next_objective.json',REPORT/'objective.json']:p.write_text(json.dumps(objective,indent=2))
    note='- Latest implementation authorization 2026-11-05: ffn_c_area; exactly independent ffn_car_AR (private accumulator data no async reset) and ffn_car_D1 (derive redundant destination remaining from source_remaining and pd_count). Keep32MAC/SRAM/Q2/int16/effective36/RNE/SS150/full cold task. A<.252275623mm2,T>=1000; prefer E<=1.8076843983968133e-05J but retain measured energy-increase tradeoffs, no percentage ceiling, no mean-power ceiling. Primary personally implements/reviews/accepts/synchronizes E/G/native ACK; no agents for implementation. No combination, extra candidate, scan or automatic publication change. Complete own CPU12/SAIF/raw/hold/final/STA/proof/W12/mapped even for negative area results. C and W/C16/IR rollback unchanged.\n\n'
    p=ROOT/'AGENTS.md';text=p.read_text(encoding='utf8')
    if note not in text:p.write_text(text.replace('# Project workspace\n\n','# Project workspace\n\n'+note,1),encoding='utf8')
    print('C_AREA_FROZEN_C',flush=True)

if __name__=='__main__':main()
