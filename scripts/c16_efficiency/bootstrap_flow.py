"""Derive an independent one-candidate acceptance flow without modifying C16."""
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
REPORT=ROOT/'reports/optimization/ffn_c16_efficiency'
BUILD=ROOT/'build/optimization/ffn_c16_efficiency'


def main():
    selection=json.loads((REPORT/'models/selection.json').read_text())
    if selection['selected'] is None:return
    name='ffn_ce_'+selection['selected']
    roots=['ffn_column_parallel','materialize_ffn_column_parallel','build_ffn_column_parallel_firmware',
           'analyze_ffn_column_parallel_firmware','prepare_ffn_column_parallel_images']
    servers=['run_ffn_column_parallel','run_ffn_column_parallel_cpu','prepare_ffn_column_parallel_complete',
        'bind_ffn_column_parallel_soc','instrument_ffn_column_parallel','measure_ffn_column_parallel',
        'audit_ffn_column_parallel_timing','check_ffn_column_parallel_activity',
        'summarize_ffn_column_parallel_counts','check_ffn_column_parallel_rtl_native',
        'evaluate_ffn_column_parallel_power','check_ffn_column_parallel_mapped','finish_ffn_column_parallel',
        'column_parallel_observers']
    created=[]
    for directory,stems in [('scripts',roots),('scripts/server',servers)]:
        for stem in stems:
            original=ROOT/directory/(stem+'.py')
            text=original.read_text(encoding='utf-8')
            text=text.replace('ffn_column_parallel','ffn_c16_efficiency').replace('column_parallel_observers','c16_efficiency_observers')
            text=text.replace('column_parallel.prepare','c16_efficiency.prepare').replace('column_parallel.observers','c16_efficiency.observers')
            if stem in ['ffn_column_parallel','run_ffn_column_parallel','finish_ffn_column_parallel','materialize_ffn_column_parallel']:
                text=text.replace('ffn_cp_C16',name)
            if stem=='ffn_column_parallel':text=text.replace('2.220596944355184e-05','1.8435083907942435e-05')
            if stem=='materialize_ffn_column_parallel':
                text=text.replace("return materialize()[1]","return materialize()[1]")
            if stem=='evaluate_ffn_column_parallel_power':text=text.replace("'ffn_cp_'","'ffn_cp_','ffn_ce_'")
            if stem=='bind_ffn_column_parallel_soc':
                at="    accelerator=(ROOT/'rtl/public_encoder/kwt_encoder_accelerator.sv').read_text()"
                insertion="    from c16_efficiency.prepare import selection,write_transform\n    if selection()=='W':shared.write_text(write_transform(shared.read_text()))\n"
                text=text.replace(at,insertion+at)
            if stem=='finish_ffn_column_parallel':
                text=text.replace('ffn_lp_IR','ffn_cp_C16').replace("ROOT/'reports/optimization/ffn_logic_power'/leaf","ROOT/'reports/optimization/ffn_column_parallel'/leaf")
                text=text.replace('IR publication changed','C16 publication changed').replace('IR发布配置未切换。保留IR和C16','C16发布配置未切换。保留C16与效率候选')
                text=text.replace('published_IR_unchanged=True','published_C16_unchanged=True')
                text=text.replace("ROOT/'scripts/column_parallel'","ROOT/'scripts/c16_efficiency'")
                text=text.replace("'scripts/column_parallel*.py'","'scripts/c16_efficiency/*.py'")
                text=text.replace("'docs/ffn-column-parallel-plan.md'","'docs/ffn-c16-efficiency-plan.md'")
                text=text.replace('32MAC列并行完整平台结果','C16效率候选完整平台结果')
            target=ROOT/directory/(stem.replace('ffn_column_parallel','ffn_c16_efficiency').replace('column_parallel_observers','c16_efficiency_observers')+'.py')
            target.write_text(text,encoding='utf-8');created.append(target.relative_to(ROOT).as_posix())
    for leaf in ['observers.py','develop.py','four_state.py']:
        text=(ROOT/'scripts/column_parallel'/leaf).read_text(encoding='utf-8')
        text=text.replace('column_parallel','c16_efficiency').replace('column_parallel_tb','c16_efficiency_tb')
        text=text.replace('ffn_logic_power_rtl_native','ffn_c16_efficiency_rtl_native')
        (ROOT/'scripts/c16_efficiency'/leaf).write_text(text,encoding='utf-8')
    for leaf in ['images','program']:
        if not (BUILD/'frozen'/leaf).exists():
            shutil.copytree(str(ROOT/'build/optimization/ffn_column_parallel/frozen'/leaf),str(BUILD/'frozen'/leaf))
    parent=json.loads((BUILD/'frozen/parent.json').read_text())
    parent['firmware']=(BUILD/'frozen/firmware').relative_to(ROOT).as_posix()
    parent['source_snapshot']=(BUILD/'frozen/rtl_sources').relative_to(ROOT).as_posix()
    parent['program']=(BUILD/'frozen/program').relative_to(ROOT).as_posix()
    parent['configuration']=json.loads((ROOT/'build/optimization/complete_soc/ffn_cp_C16/configuration.json').read_text())
    (BUILD/'frozen/parent.json').write_text(json.dumps(parent,indent=2))
    (REPORT/'flow-source-manifest.json').write_text(json.dumps(dict(candidate=name,files=created,
        parent_scripts_unchanged=True,power_workers=2,automatic_publication=False),indent=2))
    print('EFFICIENCY_FLOW_PREPARED',name,flush=True)


if __name__=='__main__':main()
