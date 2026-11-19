"""Prove the revised exact Booth intermediate for all int16 values and digits."""
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from ffn_literature_power import BUILD,REPORT,dump

def main():
    out=BUILD/'arithmetic-proof-pp18-v2';out.mkdir(parents=True,exist_ok=True)
    report=REPORT/'arithmetic-proof-pp18-v2';report.mkdir(parents=True,exist_ok=True)
    source=out/'partial18.sv'
    source.write_text('''module lit_pp18(input signed [15:0] value,input [2:0] code,output pass);
    wire signed [17:0] positive=18'($signed(value));
    wire signed [17:0] negative=-positive;
    reg signed [17:0] partial;
    always @*begin
        case(code)
            3'b001,3'b010:partial=positive;
            3'b011:partial=positive<<<1;
            3'b100:partial=negative<<<1;
            3'b101,3'b110:partial=negative;
            default:partial=0;
        endcase
    end
    wire signed [3:0] coefficient=$signed({1'b0,code[0]})+$signed({1'b0,code[1]})-
        ($signed({1'b0,code[2]})<<<1);
    wire signed [35:0] expected=36'($signed(value))*36'($signed(coefficient));
    assign pass=36'($signed(partial))==expected;
endmodule
''')
    smt=out/'partial18.smt2'
    with (report/'smt-export.log').open('w') as log:
        subprocess.run(['yosys','-Q','-p','read_verilog -sv '+source.relative_to(ROOT).as_posix()+
            '; prep -top lit_pp18; write_smt2 -wires '+smt.relative_to(ROOT).as_posix()],
            cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    query=out/'partial18-z3.smt2'
    query.write_text(smt.read_text()+'\n(declare-fun proof_state () |lit_pp18_s|)\n(assert (|lit_pp18_h| proof_state))\n(assert (not (|lit_pp18_n pass| proof_state)))\n(check-sat)\n')
    with (report/'z3.log').open('w') as log:
        subprocess.run(['z3',str(query)],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    passed=(report/'z3.log').read_text().strip()=='unsat'
    dump(report/'result.json',dict(passed=passed,method='Yosys SMT2 and Z3',
        obligation='All signed int16 values, all radix-4 Booth digits, exact signed18 partial before signed36 shift',
        original_compression_and_reconstruction_proof='reports/optimization/ffn_literature_power/arithmetic-proof/result.json'))
    if not passed:raise RuntimeError('Read the partial18 proof log')
    print('LITERATURE_PP18_PROOF_PASS',flush=True)

if __name__=='__main__':main()
