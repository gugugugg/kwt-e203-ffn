"""Create this round's independent low-level flow once; retain all historical scripts."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def main():
    roots=['build_ffn_c16_efficiency_firmware','analyze_ffn_c16_efficiency_firmware','prepare_ffn_c16_efficiency_images']
    servers=['run_ffn_c16_efficiency_cpu','prepare_ffn_c16_efficiency_complete','bind_ffn_c16_efficiency_soc',
        'instrument_ffn_c16_efficiency','measure_ffn_c16_efficiency','audit_ffn_c16_efficiency_timing','check_ffn_c16_efficiency_activity',
        'summarize_ffn_c16_efficiency_counts','check_ffn_c16_efficiency_rtl_native','evaluate_ffn_c16_efficiency_power','check_ffn_c16_efficiency_mapped','c16_efficiency_observers']
    for directory,names in [('scripts',roots),('scripts/server',servers)]:
        for stem in names:
            text=(ROOT/directory/(stem+'.py')).read_text(encoding='utf-8')
            text=text.replace('ffn_c16_efficiency','ffn_w_energy').replace('c16_efficiency_observers','w_energy_observers').replace('c16_efficiency_gate_observers','w_energy_gate_observers').replace('c16_efficiency.','w_energy.')
            if stem=='bind_ffn_c16_efficiency_soc':
                text=text.replace("from w_energy.prepare import selection,write_transform\n    if selection()=='W':shared.write_text(write_transform(shared.read_text()))",'from w_energy.prepare import write_transform\n    shared.write_text(write_transform(shared.read_text()))')
            if stem=='evaluate_ffn_c16_efficiency_power':text=text.replace("'ffn_ce_'","'ffn_ce_','ffn_wen_'")
            if stem=='build_ffn_c16_efficiency_firmware':text=text.replace("REPORT/'firmware-reuse.json'","REPORT/'firmware-reuse'/(name+'.json')")
            target=ROOT/directory/(stem.replace('ffn_c16_efficiency','ffn_w_energy').replace('c16_efficiency_observers','w_energy_observers')+'.py')
            target.write_text(text,encoding='utf-8')
    for leaf in ['observers.py','develop.py','four_state.py']:
        text=(ROOT/'scripts/c16_efficiency'/leaf).read_text(encoding='utf-8').replace('c16_efficiency','w_energy')
        if leaf=='develop.py':
            text=text.replace('import ast','import argparse\nimport ast').replace('manifest, source = prepare()',"parser=argparse.ArgumentParser();parser.add_argument('variant');args=parser.parse_args()\n    manifest, source = prepare(args.variant)")
            text=text.replace("out = BUILD/'development'","out = BUILD/'development'/args.variant").replace("report = REPORT/'development'","report = REPORT/'development'/args.variant")
        if leaf=='four_state.py':
            text=text.replace('import json','import argparse\nimport json').replace("source=ROOT/'build/optimization/rtl_sources/ffn_ce_W'","parser=argparse.ArgumentParser();parser.add_argument('variant');args=parser.parse_args()\n    source=ROOT/'build/optimization/rtl_sources'/args.variant")
            text=text.replace("out=BUILD/'development'","out=BUILD/'development'/args.variant").replace("report=REPORT/'development'","report=REPORT/'development'/args.variant")
        (ROOT/'scripts/w_energy'/leaf).write_text(text,encoding='utf-8')

if __name__=='__main__':main()
