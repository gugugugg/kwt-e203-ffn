"""Create the independently authorized final C energy flow from the accepted tools."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def transform(text):
    return text.replace('ffn_c_energy','ffn_c_final_energy').replace('ffn_cen_','ffn_cfe_').replace('c_energy','c_final_energy').replace('C_ENERGY','C_FINAL_ENERGY').replace('c-energy','c-final-energy')

def main():
    roots=['build_ffn_c_energy_firmware','analyze_ffn_c_energy_firmware','prepare_ffn_c_energy_images','materialize_ffn_c_energy','ffn_c_energy']
    servers=['run_ffn_c_energy','run_ffn_c_energy_cpu','prepare_ffn_c_energy_complete','bind_ffn_c_energy_soc','instrument_ffn_c_energy','measure_ffn_c_energy','audit_ffn_c_energy_timing','check_ffn_c_energy_activity','summarize_ffn_c_energy_counts','check_ffn_c_energy_rtl_native','evaluate_ffn_c_energy_power','check_ffn_c_energy_mapped','c_energy_observers','finish_ffn_c_energy']
    local=['develop.py','four_state.py','audit_final.py','install_accepted.py','receive_archive.py','native_install.py','native_start.py','native_preflight.py','native_status.py','native_acknowledge.py','native_close_delivery.py','package_native.py','package_files.py','send_native_saved.py']
    for directory,names in [('scripts',[s+'.py' for s in roots]),('scripts/server',[s+'.py' for s in servers]),('scripts/c_energy',local)]:
        for leaf in names:
            p=ROOT/directory/leaf
            text=transform(p.read_text(encoding='utf8'))
            if leaf=='finish_ffn_c_energy.py':
                text=text.replace("ROOT/'reports/optimization/ffn_c_final_energy'/leaf","ROOT/'reports/optimization/ffn_w_energy'/leaf")
            if leaf=='evaluate_ffn_c_energy_power.py':
                text=text.replace("'ffn_cfe_'","'ffn_cen_','ffn_cfe_'")
            if leaf=='package_native.py':
                text=text.replace("'scripts/w_energy/*.py'","'scripts/c_energy/*.py','scripts/w_energy/*.py'")
            if leaf=='native_status.py':text=text.replace("['ffn_cfe_SL']","['ffn_cfe_SS','ffn_cfe_O1']")
            if leaf in ['develop.py','four_state.py','package_native.py']:text=text.replace('c_final_energy_tb.sv','c_final_energy_tb.sv')
            dest=ROOT/transform(directory)/transform(leaf);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text,encoding='utf8')
    p=ROOT/'scripts/server/export_ffn_c_energy_evidence.tcl'
    (ROOT/'scripts/server/export_ffn_c_final_energy_evidence.tcl').write_text(transform(p.read_text()))
    print('C_FINAL_ENERGY_FLOW_CREATED',flush=True)

if __name__=='__main__':main()
