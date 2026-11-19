"""Compositional bit-vector checks for the exact new arithmetic mechanisms."""
from pathlib import Path
import json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from ffn_literature_power import REPORT,BUILD,dump

def main():
    out=BUILD/'arithmetic-proof';out.mkdir(parents=True,exist_ok=True)
    report=REPORT/'arithmetic-proof';report.mkdir(parents=True,exist_ok=True)
    text='''module lit_proof(input [35:0] x,y,z,w,input [27:0] n,input [31:0] p,
        input [15:0] value,input [2:0] code,input signed [17:0] multiplicand,output pass);
    wire [15:0] encoded={value[15],value[14:0]^{15{value[15]}}};
    wire [15:0] decoded={encoded[15],encoded[14:0]^{15{encoded[15]}}};
    wire [35:0] csa_s=x^y^z;
    wire [35:0] csa_c=((x&y)|(x&z)|(y&z))<<1;
    wire p_fits=p[31:27]=={5{p[27]}};
    wire signed [28:0] ns={n[27],n}+{p[27],p[27:0]};
    wire flush=p_fits&&(ns[28]!=ns[27]);
    wire [27:0] new_n=!p_fits?n:(flush?p[27:0]:ns[27:0]);
    wire [35:0] new_w=!p_fits?(w+36'($signed(p))):(flush?(w+36'($signed(n))):w);
    wire [35:0] before_value=w+36'($signed(n));
    wire [35:0] after_value=new_w+36'($signed(new_n));
    reg signed [35:0] unshifted;
    reg signed [2:0] coefficient;
    always @*begin
        case(code)
            3'b001,3'b010:begin unshifted=36'($signed(multiplicand));coefficient=1;end
            3'b011:begin unshifted=36'($signed(multiplicand))<<<1;coefficient=2;end
            3'b100:begin unshifted=-(36'($signed(multiplicand))<<<1);coefficient=-2;end
            3'b101,3'b110:begin unshifted=-(36'($signed(multiplicand)));coefficient=-1;end
            default:begin unshifted=0;coefficient=0;end
        endcase
    end
    wire [16:0] ext={value,1'b0};
    wire [35:0] reconstruction[0:8];
    assign reconstruction[0]=0;
    generate for(genvar d=0;d<8;d=d+1)begin: recode
        wire [2:0] bits=ext[d*2+:3];
        wire signed [3:0] digit=$signed({1'b0,bits[0]})+$signed({1'b0,bits[1]})-
            ($signed({1'b0,bits[2]})<<<1);
        assign reconstruction[d+1]=reconstruction[d]+(36'($signed(digit))<<<(2*d));
    end endgenerate
    assign pass=(decoded==value)&&((csa_s+csa_c)==(x+y+z))&&
        (after_value==(before_value+36'($signed(p))))&&
        (unshifted==36'(multiplicand*coefficient))&&
        (reconstruction[8]==36'($signed(value)));
endmodule
'''
    source=out/'compositional.sv';source.write_text(text)
    smt=out/'compositional.smt2'
    script='read_verilog -sv '+source.relative_to(ROOT).as_posix()+'; prep -top lit_proof; write_smt2 -wires '+smt.relative_to(ROOT).as_posix()
    with (report/'smt-export.log').open('w') as log:
        subprocess.run(['yosys','-Q','-p',script],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    query=smt.read_text()+'\n(declare-fun proof_state () |lit_proof_s|)\n(assert (|lit_proof_h| proof_state))\n(assert (not (|lit_proof_n pass| proof_state)))\n(check-sat)\n'
    target=out/'compositional-z3.smt2';target.write_text(query)
    with (report/'z3.log').open('w') as log:
        subprocess.run(['z3',str(target)],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    passed=(report/'z3.log').read_text().strip()=='unsat'
    dump(report/'result.json',dict(passed=passed,method='Yosys SMT2 export and Z3 compositional bit-vector proof',
        obligations=['All 16-bit XOR-MSB values are reversible','Exact 36-bit 3:2 compression',
            'M28 invariant for arbitrary 36-bit W, 28-bit N and 32-bit P',
            'Exact Booth digit multiples including +/-2','Signed 16-bit Booth reconstruction'],
        composition='Distributivity of multiplication over eight reconstructed signed digits, 36-bit modular shift/add, repeated exact CSA and final carry propagation',
        source=source.relative_to(ROOT).as_posix(),scope='Arithmetic proof, separate from real-CPU and mapped implementation acceptance'))
    if not passed:raise RuntimeError('Read the arithmetic SMT export and Z3 log')
    print('LITERATURE_ARITHMETIC_PROOF_PASS',flush=True)

if __name__=='__main__':main()
