"""Create the independent C area flow from the completed whole-SoC tools."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def transform(text):
    return text.replace('ffn_c_final_energy','ffn_c_area').replace('ffn_cfe_','ffn_car_').replace('c_final_energy','c_area').replace('C_FINAL_ENERGY','C_AREA').replace('c-final-energy','c-area').replace('ffn_car_SS','ffn_car_AR').replace('ffn_car_O1','ffn_car_D1')

def main():
    roots=['build_ffn_c_final_energy_firmware','analyze_ffn_c_final_energy_firmware','prepare_ffn_c_final_energy_images','materialize_ffn_c_final_energy','ffn_c_final_energy']
    servers=['run_ffn_c_final_energy','run_ffn_c_final_energy_cpu','prepare_ffn_c_final_energy_complete','bind_ffn_c_final_energy_soc','instrument_ffn_c_final_energy','measure_ffn_c_final_energy','audit_ffn_c_final_energy_timing','check_ffn_c_final_energy_activity','summarize_ffn_c_final_energy_counts','check_ffn_c_final_energy_rtl_native','evaluate_ffn_c_final_energy_power','check_ffn_c_final_energy_mapped','c_final_energy_observers','finish_ffn_c_final_energy']
    local=['freeze.py','develop.py','four_state.py','local_acceptance.py','audit_final.py','install_accepted.py','receive_archive.py','native_install.py','native_start.py','native_preflight.py','native_status.py','native_acknowledge.py','native_close_delivery.py','package_native.py','package_files.py','send_native_saved.py','ack_observer.py','native_final_inputs.py','native_cpu_snapshot.py','native_brief.py','native_gate_status.py','sync_control_archive.py']
    for directory,names in [('scripts',[x+'.py' for x in roots]),('scripts/server',[x+'.py' for x in servers]),('scripts/c_final_energy',local)]:
        for leaf in names:
            src=ROOT/directory/leaf;dest=ROOT/transform(directory)/transform(leaf)
            if dest.exists():raise RuntimeError('Read existing area source before overwriting '+str(dest))
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(transform(src.read_text(encoding='utf8')),encoding='utf8')
    for leaf in ['c_final_energy_phase_inventory.py','c_final_energy_phase_connectivity.py','c_final_energy_phase_prepare.py','c_final_energy_phase_review.py','assemble_ffn_c_final_energy_review.py','check_ffn_c_final_energy_probe.py']:
        dest=ROOT/'scripts'/transform(leaf);dest.write_text(transform((ROOT/'scripts'/leaf).read_text()),encoding='utf8')
    for leaf in ['query_ffn_c_final_energy_segments.py','query_ffn_c_final_energy_additional_segments.py','query_ffn_c_final_energy_corrected_phase.py','export_ffn_c_final_energy_evidence.tcl']:
        dest=ROOT/'scripts/server'/transform(leaf);dest.write_text(transform((ROOT/'scripts/server'/leaf).read_text()),encoding='utf8')
    print('C_AREA_INDEPENDENT_FLOW_CREATED',flush=True)

if __name__=='__main__':main()
