"""Verify the exact three-row datapath and build the real E203 driver."""
import json
from pathlib import Path
import re
import shutil
import subprocess
from candidate import ROOT, REPORT, NAME

PARENT = 'ffn_ara_SR'
CORE = 'dut.core'


def observer(text):
    text = re.sub(r'for\(genvar (jp_lane|car_lane|lane_id)=0;\1<32;',
                  lambda m:m[0].replace('<32','<48'),text)
    start=text.index('    generate for(genvar cp_row=0;')
    end=text.index('    end endgenerate',start)+len('    end endgenerate')
    core=re.search(r'posedge (\S+\.core)\.clk',text[start:end])[1]
    block="""    generate for(genvar cp_row=0;cp_row<3;cp_row=cp_row+1)begin: r3o_operands
        reg captured=0;
        reg [15:0] expected_operand;
        always @(posedge CORE.clk)begin
            captured<=CORE.rst_n&&CORE.capture_operands;
            if(CORE.capture_operands)expected_operand<=CORE.ap_input_rdata[cp_row*16+:16];
        end
        for(genvar cp_copy=0;cp_copy<2;cp_copy=cp_copy+1)begin: copies
            always @(negedge CORE.clk)if(CORE.rst_n&&captured)
                if(CORE.jp_input_return[(cp_row*2+cp_copy)*16+:16]!==expected_operand)
                    $fatal(1,"R3O registered operand differs");
        end
    end endgenerate"""
    return text[:start]+block.replace('CORE',core)+text[end:]


def run(command, log, cwd=ROOT):
    with log.open('w') as stream:
        subprocess.check_call([str(x) for x in command],cwd=str(cwd),stdout=stream,stderr=subprocess.STDOUT)


def firmware():
    old=ROOT/'build/optimization/firmware'/PARENT
    new=old.with_name(NAME)
    source=new/'input-files'
    if not source.exists():
        shutil.copytree(str(old/'input-files'),str(source))
    cfg=json.loads((old/'firmware.json').read_text())
    elf=new/'firmware.elf'
    binary=new/'firmware.bin'
    argv=cfg['compile_and_link_argv']
    argv=[item.replace('-DKWU_ROW_GROUP=2','-DKWU_ROW_GROUP=3') for item in argv[:-1]]+[str(elf)]
    run(argv,REPORT/'firmware-build.log',source)
    run([cfg['objcopy_argv'][0],'-O','binary',elf,binary],REPORT/'firmware-objcopy.log',source)
    run([cfg['disassembly_argv'][0],'-d',elf],new/'disassembly.txt',source)
    raw=binary.read_bytes()
    image=raw+bytes(262144-len(raw))
    (new/'firmware_itcm.hex').write_text(''.join('%016x\n'%int.from_bytes(image[i:i+8],'little')
                                                 for i in range(0,len(image),8)))
    record=dict(row_group=3,descriptor_count=68,input_words=96,output_words=384,
                compile_and_link_argv=argv,firmware_bytes=len(raw),boot_words=(len(raw)+7)//8,
                frozen_input_sources=all(p.read_bytes()==(old/'input-files'/p.relative_to(source)).read_bytes()
                                         for p in source.rglob('*') if p.is_file()))
    (new/'firmware.json').write_text(json.dumps(record,indent=2)+'\n')
    (REPORT/'firmware.json').write_text(json.dumps(record,indent=2)+'\n')


def main():
    parent=ROOT/'build/optimization/rtl'/PARENT
    work=ROOT/'build/optimization/rtl'/NAME
    work.mkdir(exist_ok=True)
    bench=work/'loading_dma_tb.sv'
    bench.write_text(observer((parent/bench.name).read_text()))
    source=ROOT/'build/optimization/rtl_sources'/NAME
    files=[ROOT/'rtl'/name for name in ('kwt_sram16x1024_model.sv','kwt_spmem16.sv','kwt_requantize.sv')]
    files+=sorted((source/'encoder').glob('*.sv'))+sorted((source/'encoder_bus').glob('*.sv'))+[bench]
    target=work/'verilator'
    run(['verilator_bin.exe','--cc','--exe','--main','--timing','--compiler','gcc','-Wno-fatal',
         '--top-module','row_reuse_tb','--output-split','20000','--Mdir',target,
         '-I'+str(source/'encoder')]+files,REPORT/'local-elaborate.log')
    run(['mingw32-make','-C',target,'-f','Vrow_reuse_tb.mk',
         'VERILATOR_ROOT=E:/xpian/tools/oss-cad-suite/share/verilator',
         'PYTHON3=E:/xpian/.venv/Scripts/python.exe','-j','4'],REPORT/'local-build.log')
    scenarios=[]
    for name,options in [('actual12',[]),('mixed_paused',['+MIXED']),('single',['+SINGLE'])]:
        log=REPORT/('local-'+name+'.log')
        run([target/'Vrow_reuse_tb.exe','+VECTOR_DIR='+str(parent/'native_vectors'),
             '+ROW_GROUP=3','+STREAM','+DOUBLE']+options,log)
        text=log.read_text()
        if text.count('FFN_NEXT_RTL_PASS layer=')!=12 or 'FFN_NEXT_RTL_ALL_PASS' not in text:
            raise RuntimeError('Incomplete R3O golden regression: '+name)
        scenarios.append(name)
        print('R3O_LOCAL_PASS',name,flush=True)
    firmware()
    (REPORT/'local-acceptance.json').write_text(json.dumps(dict(passed=True,scenarios=scenarios,
        cases_per_scenario=12,outputs_per_case=25344,lanes=48,weight_banks=16),indent=2)+'\n')

if __name__=='__main__':
    main()
