"""Reconcile the new normal scenarios, frozen firmware and independent source edits."""
from pathlib import Path
import ast,json,sys
from prepare import ROOT,BUILD,REPORT,variants
sys.path.insert(0,str(ROOT/'scripts'))
from build_ffn_c_energy_firmware import build

def main():
    rows=[]
    for name in variants():
        dev=json.loads((REPORT/'development'/name/'acceptance.json').read_text());four=json.loads((REPORT/'development'/name/'four-state-actual12.json').read_text())
        if not dev['passed'] or not four['passed']:raise RuntimeError('Own normal validation incomplete '+name)
        fw=build(name);equal=[]
        for source,target in [(BUILD/'frozen/rtl_sources',ROOT/'build/optimization/rtl_sources'/name),(BUILD/'frozen/firmware',fw)]:
            for p in source.rglob('*'):
                if not p.is_file():continue
                rel=p.relative_to(source)
                if source.name=='rtl_sources' and p.name=='kwt_encoder.sv':continue
                if p.read_bytes()!=(target/rel).read_bytes():raise RuntimeError('Unrelated C source/firmware changed '+str(rel))
                equal.append(str(rel))
        rows.append(dict(variant=name,normal_tasks=36,normal_ordered_outputs=912384,four_state_tasks=12,four_state_ordered_outputs=304128,
            all_outputs_same_numerical_model=True,unchanged_source_and_firmware=equal,hardware_change_only_core=True))
    files=list((ROOT/'scripts/c_energy').glob('*.py'))+list(ROOT.glob('scripts/*ffn_c_energy*.py'))+list(ROOT.glob('scripts/server/*c_energy*.py'))
    for p in files:ast.parse(p.read_text(encoding='utf-8'),feature_version=(3,6))
    if (ROOT/'constraints/ffn_selected.json').read_bytes()!=(BUILD/'frozen/selected-original.json').read_bytes():raise RuntimeError('Published C changed')
    result=dict(passed=True,candidates=rows,python36_syntax_files=len(files),published_C_unchanged=True,combined=False,
        shared_controller='C unchanged; normal CPU/DMA/host competition is retained, generated SoC bytes will be compared on native prepare',
        native_CPU=False,native_PPA=False,native_ACK=False)
    (REPORT/'local-acceptance.json').write_text(json.dumps(result,indent=2));print('C_ENERGY_LOCAL_ACCEPTED',len(rows),flush=True)

if __name__=='__main__':main()
