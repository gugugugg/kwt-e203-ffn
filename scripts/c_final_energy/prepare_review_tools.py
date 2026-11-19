"""Copy only structural analysis tools; each new final supplies its own evidence."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def transform(text):return text.replace('ffn_c_energy','ffn_c_final_energy').replace('ffn_cen_','ffn_cfe_').replace('c_energy','c_final_energy').replace('C_ENERGY','C_FINAL_ENERGY').replace('c-energy','c-final-energy')
def main():
    local=['native_final_inputs.py','native_cpu_snapshot.py']
    root=['c_energy_phase_inventory.py','c_energy_phase_connectivity.py','c_energy_phase_prepare.py','c_energy_phase_review.py','assemble_ffn_c_energy_review.py','check_ffn_c_energy_probe.py']
    server=['query_ffn_c_energy_segments.py','query_ffn_c_energy_additional_segments.py','query_ffn_c_energy_corrected_phase.py']
    for directory,leaves in [('scripts/c_energy',local),('scripts',root),('scripts/server',server)]:
        for leaf in leaves:
            src=ROOT/directory/leaf;dest=ROOT/transform(directory)/transform(leaf);dest.write_text(transform(src.read_text()),encoding='utf8')
    print('C_FINAL_ENERGY_STRUCTURAL_REVIEW_TOOLS_CREATED',flush=True)
if __name__=='__main__':main()
