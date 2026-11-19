"""Accept normal and four-state results and byte-compare unaffected C dependencies."""
from pathlib import Path
import ast,json,sys
from prepare import ROOT,BUILD,REPORT,variants
sys.path.insert(0,str(ROOT/'scripts'))
from build_ffn_c_final_energy_firmware import build

def main():
    rows=[]
    for name in variants():
        dev=json.loads((REPORT/'development'/name/'acceptance.json').read_text());four=json.loads((REPORT/'development'/name/'four-state-actual12.json').read_text())
        if not dev['passed'] or not four['passed']:raise RuntimeError('Own normal validation incomplete '+name)
        fw=build(name);equal=[];changes=[]
        allowed='kwt_encoder.sv' if name.endswith('_SS') else 'kwt_joint_output_queue.sv'
        for source,target in [(BUILD/'frozen/rtl_sources',ROOT/'build/optimization/rtl_sources'/name),(BUILD/'frozen/firmware',fw)]:
            for p in source.rglob('*'):
                if not p.is_file():continue
                rel=p.relative_to(source)
                if p.read_bytes()!=(target/rel).read_bytes():
                    if source.name!='rtl_sources' or p.name!=allowed:raise RuntimeError('Unrelated C source/firmware changed '+str(rel))
                    changes.append(str(rel))
                else:equal.append(str(rel))
        rows.append(dict(variant=name,normal_tasks=36,four_state_tasks=12,outputs_per_task=25344,ordered_trace=True,all_outputs_same_numerical_model=True,changed_sources=changes,unchanged_source_and_firmware=equal))
    files=list((ROOT/'scripts/c_final_energy').glob('*.py'))+list(ROOT.glob('scripts/*ffn_c_final_energy*.py'))+list(ROOT.glob('scripts/server/*c_final_energy*.py'))
    for p in files:ast.parse(p.read_text(encoding='utf8'),feature_version=(3,6))
    if (ROOT/'constraints/ffn_selected.json').read_bytes()!=(BUILD/'frozen/selected-original.json').read_bytes():raise RuntimeError('Published C changed')
    result=dict(passed=True,candidates=rows,python36_syntax_files=len(files),published_C_unchanged=True,combined=False,native_CPU=False,native_PPA=False,native_ACK=False)
    (REPORT/'local-acceptance.json').write_text(json.dumps(result,indent=2));print('C_FINAL_ENERGY_LOCAL_ACCEPTED',len(rows),flush=True)

if __name__=='__main__':main()
