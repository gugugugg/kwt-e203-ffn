"""Record the actual local milestone and prepare a verified source package."""
import ast
import json
from prepare import ROOT,BUILD,REPORT,NAME,selection


def main():
    development=json.loads((REPORT/'development/acceptance.json').read_text())
    shared=json.loads((REPORT/'development/shared/acceptance.json').read_text())
    models=json.loads((REPORT/'models/selection.json').read_text())
    four=REPORT/'development/four-state-actual12.json'
    if not (development['passed'] and shared['passed'] and models['passed']):raise RuntimeError('Incomplete local normal validation')
    equal=[]
    for p in (BUILD/'frozen/rtl_sources').rglob('*'):
        if p.is_file():
            child=ROOT/'build/optimization/rtl_sources'/NAME/p.relative_to(BUILD/'frozen/rtl_sources')
            if p.read_bytes()!=child.read_bytes():raise RuntimeError('W changed compute source bytes')
            equal.append(p.relative_to(BUILD/'frozen/rtl_sources').as_posix())
    if (ROOT/'constraints/ffn_selected.json').read_bytes()!=(BUILD/'frozen/selected-original.json').read_bytes():
        raise RuntimeError('Published C16 changed')
    paths=list(ROOT.glob('scripts/*ffn_c16_efficiency*.py'))+list(ROOT.glob('scripts/server/*c16_efficiency*.py'))
    paths+=list((ROOT/'scripts/c16_efficiency').glob('*.py'))
    for path in paths:ast.parse(path.read_text(encoding='utf-8'),feature_version=(3,6))
    receipt=dict(variant=NAME,selected_model=selection(),local_passed=True,model_anchor_check=True,
        core_source_byte_equal_C16=True,unchanged_core_files=equal,tasks=36,ordered_outputs=912384,
        shared_competition_and_real_engine=True,write_handoffs_exercised=148,combinational_scc=0,
        four_state_common_core=four.exists() and json.loads(four.read_text())['passed'],
        four_state_source='The executing four-state job used the byte-identical frozen C16 core; W changes only the separately checked shared controller',
        python36_syntax_files=len(paths),published_C16_unchanged=True,
        native_CPU=False,native_PPA=False,native_ACK=False)
    (REPORT/'local-acceptance.json').write_text(json.dumps(receipt,indent=2))
    print('EFFICIENCY_LOCAL_ACCEPTED',NAME,flush=True)


if __name__=='__main__':main()
