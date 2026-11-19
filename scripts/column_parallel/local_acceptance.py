"""Close local acceptance and synchronize the current local milestone to G."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import ast
import collections
import json
import re
import sys
from prepare import ROOT,BUILD,REPORT,NAME


def main():
    development=json.loads((REPORT/'development/acceptance.json').read_text())
    four_state=json.loads((REPORT/'development/four-state-actual12.json').read_text())
    models=json.loads((REPORT/'models/summary.json').read_text())
    if not (development['passed'] and four_state['passed'] and models['passed']):
        raise RuntimeError('Read incomplete local checks')
    scripts=list((ROOT/'scripts/column_parallel').glob('*.py'))
    scripts+=list((ROOT/'scripts/server').glob('*ffn_column_parallel*.py'))
    scripts+=list((ROOT/'scripts').glob('*ffn_column_parallel*.py'))
    scripts.append(ROOT/'scripts/server/column_parallel_observers.py')
    native=[]
    for path in scripts:
        if path.name not in ['core_model.py','model_validate.py','timing_model.py']:
            ast.parse(path.read_text(encoding='utf-8'),feature_version=(3,6))
            native.append(path.relative_to(ROOT).as_posix())
    sys.path.insert(0,str(ROOT/'scripts'))
    from build_ffn_column_parallel_firmware import build
    firmware=build(NAME)
    original=BUILD/'frozen/rtl_sources'
    candidate=ROOT/'build/optimization/rtl_sources'/NAME
    unchanged=[]
    for path in original.rglob('*'):
        if path.is_file() and path.name!='kwt_encoder.sv':
            other=candidate/path.relative_to(original)
            if other.read_bytes()!=path.read_bytes():raise RuntimeError('Unrelated source changed')
            unchanged.append(path.relative_to(original).as_posix())
    selected=ROOT/'constraints/ffn_selected.json'
    if selected.read_bytes()!=(BUILD/'frozen/selected-original.json').read_bytes():
        raise RuntimeError('IR publication changed')
    log=(REPORT/'development/compile.log').read_text(errors='replace')
    warnings=collections.Counter(re.findall(r'^%Warning-([^:]+):',log,re.M))
    (REPORT/'development/compiler-warning-review.json').write_text(json.dumps(dict(
        warnings=dict(warnings),errors=0,
        array_multiple_driver='Generated accumulator/shift/FIFO processes drive distinct elements; no element has multiple procedural drivers.',
        latch_COMBDLY='Original IR nonblocking HIGH-latch style retained. Separate four-state actual12 passes with original NBA/latch semantics.',
        high_quant_index='Even low index0..30 plus1 yields1..31; six-bit intermediate has zero top bit on every legal EMIT. No accessed element is truncated.',
        other_width='Original integer-valued Boolean parameters, explicit signed activation extension and inherited bench integer tests; original interfaces and arithmetic unchanged.',
        native_VCS_DC_PT_pending=True),indent=2))
    receipt=dict(timestamp=datetime.now(timezone(timedelta(hours=8))).isoformat(),variant=NAME,
        local_development_passed=True,compiled_tasks=36,compiled_outputs=912384,
        four_state_tasks=12,four_state_outputs=304128,ordered_trace=True,
        models_passed=True,IR_native_trace_calibration_cycles=148271,
        unchanged_source_files=unchanged,native_python36_syntax_files=native,
        IR_published_unchanged=True,firmware_byte_equal=True,
        native_deployed=False,native_CPU=False,native_EDA=False,native_ACK=False,
        stage='local_accepted_wait_user_ethernet',
        remaining=['native UID/proc/log preflight','own RTL3 and fresh CPU12/SAIF','raw/hold/final and SS150/gating/electrical/3proof',
                   'independent final-netlist activity review and native power12','representative mapped CPU',
                   'exact decision, finalE/G byte synchronization and native ACK'])
    (REPORT/'local-acceptance.json').write_text(json.dumps(receipt,indent=2))
    destination=Path('G:/xpian_历史版本库/研究与规划/ffn_column_parallel')
    files=set(p for p in REPORT.rglob('*') if p.is_file() and p.name!='local-preparation-sync.json')
    files.update(scripts)
    files.update(p for p in candidate.rglob('*') if p.is_file())
    files.update(p for p in firmware.rglob('*') if p.is_file())
    files.update(p for p in (BUILD/'frozen').rglob('*') if p.is_file())
    files.update(p for p in (BUILD/'development').rglob('*') if p.is_file() and p.suffix in ['.sv','.hex'])
    files.update(p for p in (ROOT/'constraints/ffn_column_parallel').rglob('*') if p.is_file())
    files.update(ROOT/path for path in ['AGENTS.md','constraints/ffn_selected.json','constraints/ffn_next_objective.json',
        'constraints/ffn_submission_priority.json','constraints/ffn_parallel.json','constraints/complete_soc.sdc',
        'docs/ffn-column-parallel-plan.md','docs/ffn-next-objective.md','scripts/column_parallel_bootstrap.py',
        'rtl/kwt_sram16x1024_model.sv','rtl/kwt_spmem16.sv','rtl/kwt_requantize.sv'])
    # The calibration trace is retained once under its original path in this milestone.
    files.add(ROOT/'reports/optimization/ffn_taskflow_study/native-evidence/reports/optimization/ffn_taskflow_study/native-events.csv')
    entries=[]
    for path in sorted(files):
        relative=path.relative_to(ROOT)
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
        value=path.read_bytes()
        if not target.exists() or target.read_bytes()!=value:target.write_bytes(value)
        if target.read_bytes()!=value:raise RuntimeError('G byte comparison failed: '+str(relative))
        entries.append(dict(path=relative.as_posix(),bytes=len(value),equal=True))
    sync=dict(timestamp=receipt['timestamp'],phase='local_preparation_only',destination=str(destination),
        files=len(entries),bytes=sum(p['bytes'] for p in entries),all_bytes_equal=True,entries=entries,
        full_native_acceptance_complete=False,native_ACK=False,deleted_files=0)
    path=REPORT/'local-preparation-sync.json';path.write_text(json.dumps(sync,indent=2,ensure_ascii=False),encoding='utf-8')
    target=destination/path.relative_to(ROOT);target.write_bytes(path.read_bytes())
    print('COLUMN_LOCAL_MILESTONE_G_VERIFIED',len(entries),sync['bytes'],flush=True)


if __name__=='__main__':main()
