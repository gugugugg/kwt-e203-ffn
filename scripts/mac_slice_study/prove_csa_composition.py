"""Close the word reduction by the universal one-bit CSA identity and lifting."""
import json
import subprocess
from prepare import ROOT,OUT,REPORT,csa

source=(OUT/'SHARE4/mac_slice.sv').read_text()
actual=source[source.index(' wire [35:0] stage1_s'):source.index(' always @(posedge accumulator_clk')]
expected=csa('stage1','part0','part1','part2')+csa('stage2','stage1_s','stage1_c','part3')+csa('stage3','stage2_s','stage2_c','accumulator[n]')+' wire [35:0] next_acc=stage3_s+stage3_c;\n'
assert actual==expected
directory=REPORT/'compositional-proof'
rtl=directory/'csa-bit.sv'
rtl.write_text('''module proof(input x,y,z,output proof);
wire s=x^y^z;
wire c=(x&y)|(x&z)|(y&z);
wire [1:0] expected={1'b0,x}+{1'b0,y}+{1'b0,z};
assign proof={c,s}==expected;
endmodule
''')
log=directory/'csa-bit.log'
with log.open('w') as stream:
    p=subprocess.run(['yosys','-p','read_verilog %s; prep -top proof; techmap; opt; sat -verify -prove proof 1 -show-inputs'%rtl.relative_to(ROOT).as_posix()],
        cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT)
assert p.returncode==0 and 'SUCCESS' in log.read_text()
cases=json.loads((directory/'parts.json').read_text())['cases']
assert len(cases)==64 and all(r['passed'] for r in cases)
result=dict(passed=True,fragment_cases=cases,CSA_bit_identity_formally_proven=True,CSA_source_exactly_matched=True,
    width=36,arbitrary_activation_bits=16,arbitrary_weight_bits=16,arbitrary_feedback_bits=36,
    lifting='Multiply each bit identity x_i+y_i+z_i=s_i+2*c_i by2^i and sum i=0..35, modulo2^36. This proves the exact emitted word XOR/AND/OR/shift expression for all36-bit x,y,z.',
    stages=['part0+part1+part2 = stage1_s+stage1_c (mod2^36)',
        'stage1_s+stage1_c+part3 = stage2_s+stage2_c (mod2^36)',
        'stage2_s+stage2_c+feedback = stage3_s+stage3_c (mod2^36)',
        'next_acc=stage3_s+stage3_c (mod2^36)'],
    signed_decomposition='signed16(w)=d0+16*d1+256*d2+4096*signed4(d3). The64 symbolic fragment proofs cover every digit and every signed16 activation, including -32768.',
    sequential_composition='Input hold, tile selection, reset/seed/MAC priority, pair gate and quantization logic are unchanged. Equal initial/seed state and equal modular next state imply equal accumulator state on every enabled edge.',
    full_word_solver_status='The monolithic reduction SAT and independent whole-bank native FM are separate runs, not this compositional proof.')
(REPORT/'compositional-proof-csa-lift.json').write_text(json.dumps(result,indent=2))
(directory/'exact-emitted-SHARE4.sv').write_text(source)
print('MAC_SLICE_COMPOSITIONAL_PROOF_PASS',flush=True)
