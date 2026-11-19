"""Freeze the published C16 input and the newly authorized objective."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT/'build/optimization/ffn_c16_efficiency'
REPORT = ROOT/'reports/optimization/ffn_c16_efficiency'


def main():
    frozen = BUILD/'frozen'
    frozen.mkdir(parents=True, exist_ok=True)
    state = json.loads((ROOT/'reports/optimization/ffn_column_parallel/ffn_cp_C16.json').read_text())
    manifest = json.loads((ROOT/'constraints/ffn_column_parallel/candidates/ffn_cp_C16.json').read_text())
    profile = json.loads((ROOT/state['profile']).read_text())
    parent = dict(manifest, state=state, profile=profile,
                  firmware='build/optimization/firmware/ffn_cp_C16',
                  source_snapshot='build/optimization/rtl_sources/ffn_cp_C16')
    if not (frozen/'parent.json').exists():
        (frozen/'parent.json').write_text(json.dumps(parent, indent=2))
        for folder, target in [(parent['source_snapshot'], 'rtl_sources'), (parent['firmware'], 'firmware')]:
            shutil.copytree(str(ROOT/folder), str(frozen/target))
        for original, leaf in [('constraints/ffn_selected.json','selected-original.json'),
                               ('constraints/ffn_next_objective.json','previous-objective.json'),
                               ('AGENTS.md','AGENTS-before.md')]:
            shutil.copyfile(str(ROOT/original), str(frozen/leaf))
    objective = json.loads((frozen/'previous-objective.json').read_text())
    objective.update(status='implementation_authorized', active_experiment='ffn_c16_efficiency',
                     automatic_release_switch=False,
                     user_request='Model C/W independently; implement at most one; lower energy than published C16')
    objective['fixed_reference'] = dict(variant='ffn_cp_C16', cycles=100567,
        scoring_area_mm2=0.253049045,mean_power_w=0.027496719462560937,
        mean_energy_j=1.8435083907942435e-05,
        source='reports/optimization/ffn_column_parallel/final-selection.json')
    objective['joint_target'].update(reference_variant='ffn_cp_C16',
        mean_task_energy_j_strictly_below=1.8435083907942435e-05,
        scoring_area_mm2_at_most=0.2764843225, release='C16 retained; IR rollback; no automatic switch')
    objective['selection_order']=['Full numerical/integration/SS150 acceptance',
        'E<C16, A<=0.2764843225, T>=1000', 'Report official-score tradeoff without invented group references']
    objective['previous_objective_snapshot']=(frozen/'previous-objective.json').relative_to(ROOT).as_posix()
    (ROOT/'constraints/ffn_next_objective.json').write_text(json.dumps(objective,indent=2))
    (REPORT/'objective.json').write_text(json.dumps(objective,indent=2))
    agents=ROOT/'AGENTS.md'
    paragraph='- Latest efficiency authorization 2026-11-04: compare only C(tile control handoff) and W(same-DMA write/write handoff) models against published C16. Implement at most one selected by lower aggregate12 final-commit cycles (tie C), no combination. Own namespace ffn_c16_efficiency; E<1.8435083907942435e-05J, area<=0.2764843225mm2, T>=1000; mean power may rise. Keep current C16 release and IR rollback unchanged. Primary personally implements, reviews actual activity and accepts.\n\n'
    if paragraph not in agents.read_text(encoding='utf-8'):
        agents.write_text(agents.read_text(encoding='utf-8').replace('# Project workspace\n\n','# Project workspace\n\n'+paragraph,1),encoding='utf-8')
    print('EFFICIENCY_C16_FROZEN',flush=True)


if __name__=='__main__':main()
