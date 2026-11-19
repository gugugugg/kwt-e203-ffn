"""Copy the accepted flow into a new namespace without changing historical scripts."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def transform(text):return text.replace('ffn_w_energy','ffn_c_energy').replace('ffn_wen_','ffn_cen_').replace('w_energy','c_energy').replace('W_ENERGY','C_ENERGY')
def main():
    roots=['build_ffn_w_energy_firmware','analyze_ffn_w_energy_firmware','prepare_ffn_w_energy_images','materialize_ffn_w_energy','ffn_w_energy']
    servers=['run_ffn_w_energy','run_ffn_w_energy_cpu','prepare_ffn_w_energy_complete','bind_ffn_w_energy_soc','instrument_ffn_w_energy','measure_ffn_w_energy','audit_ffn_w_energy_timing','check_ffn_w_energy_activity','summarize_ffn_w_energy_counts','check_ffn_w_energy_rtl_native','evaluate_ffn_w_energy_power','check_ffn_w_energy_mapped','w_energy_observers','finish_ffn_w_energy']
    local=['develop.py','four_state.py','observers.py','audit_final.py','install_accepted.py','receive_archive.py','native_install.py','native_start.py','native_preflight.py','native_status.py','native_acknowledge.py','native_close_delivery.py','package_native.py']
    for directory,names in [('scripts',[s+'.py' for s in roots]),('scripts/server',[s+'.py' for s in servers]),('scripts/w_energy',local)]:
        for leaf in names:
            p=ROOT/directory/leaf;text=transform(p.read_text(encoding='utf8'));destination=ROOT/transform(directory)/transform(leaf)
            if leaf=='ffn_w_energy.py':text=text.replace('ENERGY_LIMIT_J=1.822518977709749e-05','ENERGY_LIMIT_J=1.8076843983968133e-05')
            if leaf=='bind_ffn_w_energy_soc.py':text=text.replace('from c_energy.prepare import write_transform','from w_energy.prepare import write_transform')
            if leaf=='evaluate_ffn_w_energy_power.py':
                text=text.replace("'ffn_ce_','ffn_cen_'","'ffn_ce_','ffn_wen_','ffn_cen_'")
            if leaf in ['finish_ffn_w_energy.py','audit_final.py','install_accepted.py','native_install.py','native_acknowledge.py','native_close_delivery.py']:
                text=text.replace('ffn_ce_W','ffn_wen_C')
                if leaf=='finish_ffn_w_energy.py':text=text.replace("ROOT/'reports/optimization/ffn_c16_efficiency'","ROOT/'reports/optimization/ffn_w_energy'").replace('activity-mapping/native-review-W','activity-mapping/native-review-first')
            if leaf=='native_status.py':text=text.replace("['ffn_cen_C','ffn_cen_SL']","['ffn_cen_SL']")
            if leaf=='native_preflight.py':text=text.replace("'ffn_ce_W'","'ffn_wen_C'")
            if leaf=='package_native.py':text=text.replace("'scripts/c16_efficiency/*.py'","'scripts/w_energy/*.py','scripts/c16_efficiency/*.py'").replace('docs/ffn-c-energy-plan.md','docs/ffn-c-energy-plan.md')
            if leaf=='develop.py':text=text.replace('IR_release_unchanged=True','published_C_unchanged=True')
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(text,encoding='utf8')
    for leaf in ['export_ffn_w_energy_evidence.tcl']:
        text=transform((ROOT/'scripts/server'/leaf).read_text());(ROOT/'scripts/server'/transform(leaf)).write_text(text)
    print('C_ENERGY_INDEPENDENT_FLOW_CREATED',flush=True)
if __name__=='__main__':main()
