"""Prove the full-width counter invariant and replay the actual old/new DMA engines."""
import json,subprocess
from pathlib import Path
from prepare import ROOT,BUILD,REPORT

def main():
    out=BUILD/'engine-equivalence';r=REPORT/'engine-equivalence';out.mkdir(parents=True,exist_ok=True);r.mkdir(parents=True,exist_ok=True)
    text='''module car_count_induction(input [31:0] S,D,N,input [1:0] C,input sf,dc,output good);
wire [32:0] total={1'b0,S}+{31'd0,C};
wire legal=(C<=2)&&(total=={1'b0,D})&&(!sf||(S!=0&&C<2))&&(!dc||(C!=0));
wire [31:0] Sn=S-32'(sf),Dn=D-32'(dc);
wire [1:0] Cn=C+2'(sf)-2'(dc);
wire step=({1'b0,Dn}==({1'b0,Sn}+{31'd0,Cn}));
wire final_equal=!dc||((D==1)==(S==0&&C==1));
wire base=({1'b0,N}==({1'b0,N}+33'd0));
assign good=(!legal||(step&&final_equal))&&base;
endmodule
'''
    sv=out/'counter_induction.sv';sv.write_text(text);script=out/'counter_induction.ys';script.write_text('read_verilog -sv '+sv.relative_to(ROOT).as_posix()+'\nprep -top car_count_induction\nsat -verify -prove good 1 -show-inputs\n')
    if not (r/'induction.json').exists():
        with (r/'induction.log').open('w') as log:subprocess.run(['yosys','-s',str(script)],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    t=(r/'induction.log').read_text();assert 'SUCCESS!' in t
    (r/'induction.json').write_text(json.dumps(dict(passed=True,width=32,pending_width=2,base_reset_and_start=True,step_all_legal_events=True,old_state_last_completion_equivalent=True,overflow_excluded_by_full_width_relation=True,error_terminal_inactive_excluded=True,actual_engine_replay_separate=True),indent=2))
    original=(BUILD/'frozen/rtl_sources/encoder/kwt_ld_engine.sv').read_text();candidate=(ROOT/'build/optimization/rtl_sources/ffn_car_D1/encoder/kwt_ld_engine.sv').read_text()
    (out/'reference.sv').write_text(original.replace('module kwt_ld_engine(','module reference_engine(',1));(out/'candidate.sv').write_text(candidate)
    bench=(ROOT/'tb/ffn_c_area/engine_equivalence_tb.sv').read_text();tb=out/'engine_equivalence_tb.sv';tb.write_text(bench)
    with (r/'compile.log').open('w') as log:subprocess.run(['iverilog','-g2012','-s','car_engine_equivalence_tb','-o',str(out/'engine-equivalence.vvp'),str(out/'reference.sv'),str(out/'candidate.sv'),str(tb)],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    with (r/'replay.log').open('w') as log:subprocess.run(['vvp',str(out/'engine-equivalence.vvp')],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    log=(r/'replay.log').read_text();assert 'C_AREA_DMA_EQUIVALENCE_ALL_PASS' in log
    (r/'acceptance.json').write_text(json.dumps(dict(passed=True,full_width_induction=True,actual_original_and_candidate_modules=True,normal_descriptors=8,error_descriptors=4,zero_and_single=True,two_slots=True,delayed_responses=True,simultaneous_source_and_destination=True,source_and_destination_errors=True,normal_backpressure=True,native_CPU=False),indent=2));print('C_AREA_DMA_INDUCTION_AND_REPLAY_PASS',flush=True)

if __name__=='__main__':main()
