"""Prove the exact emitted coefficient/fragment RTL compositionally."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import subprocess
from prepare import ROOT,OUT,REPORT

source=(OUT/'SHARE4/mac_slice.sv').read_text()
start=source.index('generate for(genvar r=0;r<2;r=r+1)begin: coefficient_rows')
end=source.index('end endgenerate',start)+len('end endgenerate')
table=source[start:end]
parts=source[source.index(' wire signed [19:0] digit0'):source.index(' wire [35:0] stage1_s')]
reduction=source[source.index(' wire [35:0] stage1_s'):source.index(' always @(posedge accumulator_clk')]
directory=REPORT/'compositional-proof';directory.mkdir(exist_ok=True)

def one(part,digit):
    signed_digit=digit if part<3 or digit<8 else digit-16
    constant="-20'sd%d"%(-signed_digit) if signed_digit<0 else "20'sd%d"%signed_digit
    text='module proof(input signed [15:0] activation,output proof);\n'
    text+='wire [31:0] input_return={activation,activation};\n'+table+'\n'
    text+="localparam integer R=0;wire [15:0] weight_value=16'h%04x;\n"%(digit<<(4*part))
    text+=parts
    text+='wire signed [19:0] expected_product=$signed(activation)*%s;\n'%constant
    text+='wire [35:0] expected={{16{expected_product[19]}},expected_product}<<%d;\n'%(4*part)
    text+='assign proof=part%d==expected;\nendmodule\n'%part
    stem='part%d-digit%02d'%(part,digit);rtl=directory/(stem+'.sv');log=directory/(stem+'.log')
    rtl.write_text(text)
    command='read_verilog -sv %s; prep -top proof -flatten; techmap; opt; sat -verify -prove proof 1 -show-inputs'%rtl.relative_to(ROOT).as_posix()
    with log.open('w') as stream:
        p=subprocess.run(['yosys','-p',command],cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT)
    passed=p.returncode==0 and 'SUCCESS' in log.read_text()
    return dict(part=part,digit=digit,arbitrary_activation_bits=16,passed=passed,source=str(rtl.relative_to(ROOT)),log=str(log.relative_to(ROOT)))

def main():
    cases=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(one,p,d) for p in range(4) for d in range(16)]):
            result=f.result();cases.append(result)
            (directory/'parts.json').write_text(json.dumps(dict(cases=cases),indent=2))
            print('SLICE_PART_PROOF',result['part'],result['digit'],result['passed'],flush=True)
    assert all(r['passed'] for r in cases)
    rtl=directory/'reduction.sv'
    rtl.write_text('module proof(input [35:0] part0,part1,part2,part3,feedback,output proof);\n'
        +'localparam integer n=0;wire [35:0] accumulator[0:0];assign accumulator[0]=feedback;\n'
        +reduction+'\nwire [35:0] expected=part0+part1+part2+part3+feedback;\nassign proof=next_acc==expected;\nendmodule\n')
    log=directory/'reduction.log'
    with log.open('w') as stream:
        p=subprocess.run(['yosys','-p','read_verilog -sv %s; prep -top proof -flatten; techmap; opt; sat -verify -prove proof 1 -show-inputs'%rtl.relative_to(ROOT).as_posix()],
            cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT)
    passed=p.returncode==0 and 'SUCCESS' in log.read_text()
    result=dict(passed=passed,fragment_cases=cases,arbitrary_feedback_bits=36,arbitrary_reduction_terms=4,
        extraction='Exact emitted SHARE4 coefficient, fragment and reduction text',
        composition='signed16(w)=d0+16*d1+256*d2+4096*signed4(d3); multiplication distributes over these four fragments modulo2^36',
        scheduling='Unchanged latches, qualifiers, seed priority and accumulator state; checked every cycle beside IR',
        reduction_log=str(log.relative_to(ROOT)))
    (REPORT/'compositional-proof.json').write_text(json.dumps(result,indent=2));assert passed

if __name__=='__main__':main()
