"""Prove the implemented shift code against the published raw shift quantizer."""
import re
import subprocess

from prepare import BUILD, FROZEN, REPORT, ROOT, write


def main():
    work = BUILD / 'quantizer-equivalence'
    work.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'build/optimization/rtl_sources/ffn_sra_S3/encoder'
    old = (FROZEN / 'rtl_sources/encoder/kwt_ffn_requantize.sv').read_text()
    new = (source / 'kwt_ffn_requantize.sv').read_text()
    encoder = (source / 'kwt_encoder.sv').read_text()
    code = re.search(r'function automatic \[2:0\] shift_code\b.*?endfunction', encoder, re.S).group()
    miter = work / 'miter.sv'
    miter.write_text(old.replace('module kwt_ffn_requantize(', 'module frozen_sr_quantizer(') + new + """
module shift_equivalence(input signed [35:0] acc, input [7:0] raw, output equivalent);
""" + code + """
    wire signed [63:0] value={{28{acc[35]}},acc};
    wire [15:0] golden, coded, reserved;
    frozen_sr_quantizer reference_model(.value(value),.shift(raw),.result(golden));
    kwt_ffn_requantize candidate(.value(value),.shift(shift_code(raw)),.result(coded));
    kwt_ffn_requantize unused_code(.value(value),.shift(3'd7),.result(reserved));
    assign equivalent=(golden==coded)&&(reserved==16'd0);
endmodule
""")
    proof = 'read_verilog -sv miter.sv; prep -top shift_equivalence -flatten; sat -verify -prove equivalent 1 -show-inputs'
    (work / 'prove.ys').write_text(proof + '\n')
    with (REPORT / 's3-quantizer-proof.log').open('w') as log:
        subprocess.run(['yosys', '-s', 'prove.ys'], cwd=str(work), stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    bench = work / 'four_state.sv'
    bench.write_text("""
module four_state;
    reg signed [35:0] acc;
    reg [7:0] raw;
    wire equivalent;
    shift_equivalence dut(acc,raw,equivalent);
    task check(input [7:0] s, input signed [35:0] a);
        raw=s; acc=a;
        #1;
        if(equivalent !== 1'b1)$fatal(1,"S3 mismatch raw=%b acc=%0d",raw,acc);
    endtask
    initial begin
        for(integer s=0;s<256;s=s+1)begin
            check(8'(s),36'sh800000000);
            check(8'(s),36'sh7ffffffff);
            check(8'(s),36'sd0);
        end
        for(integer s=13;s<=18;s=s+1)
            for(integer q=-32769;q<=32768;q=q+1)
                if(q<=-32767 || (q>=-2 && q<=2) || q>=32766)
                    for(integer d=-1;d<=1;d=d+1)
                        check(8'(s),(36'(q)<<<s)+(36'sd1<<<(s-1))+36'(d));
        check(8'b000011x1,36'sh7ffffffff);
        check(8'b000100z0,36'sh800000000);
        check(8'bxxxxxxxx,36'sd131072);
        check(8'bzzzzzzzz,36'sd131072);
        $display("S3_QUANTIZER_FOUR_STATE_PASS");
        $finish;
    end
endmodule
""")
    with (REPORT / 's3-quantizer-four-state.log').open('w') as log:
        subprocess.run(['iverilog', '-g2012', '-s', 'four_state', '-o', 'four_state.vvp',
                        miter.name, bench.name], cwd=str(work), stdout=log,
                       stderr=subprocess.STDOUT, check=True)
        subprocess.run(['vvp', 'four_state.vvp'], cwd=str(work), stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    write(REPORT / 's3-quantizer-equivalence.json',
          dict(passed=True, proof='Yosys SAT with unrestricted signed36 accumulator and raw uint8',
               four_state='all 256 encodings at representative values, X/Z, signed ties and saturation',
               reserved_code_seven_zero=True, miter=miter.relative_to(ROOT).as_posix()))
    print('S3_QUANTIZER_EQUIVALENCE_PASS', flush=True)


if __name__ == '__main__':
    main()
