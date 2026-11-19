"""Run cycle-for-cycle reference checks at the two modified datapaths."""
import json
import os
from pathlib import Path
import subprocess
import sys

from build_ch_efficiency import CANDIDATES, PARENT, REPORT, ROOT, RTL, SOC, build

HERE = Path(__file__).resolve().parent
LOCAL = REPORT/'local'
MODELS = ROOT/'reports/optimization/ffn_literature_power/recovery/actual-compilation-sources/external-models/storage1/admin_public_dir/SRAM_Lib_2025'


def run(args, path):
    with path.open('w', encoding='utf-8') as stream:
        subprocess.run([str(arg) for arg in args], cwd=str(ROOT), stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def check(kind):
    LOCAL.mkdir(parents=True, exist_ok=True)
    attempt = LOCAL/(kind.lower()+'-attempt-%02d' % (1+len(list(LOCAL.glob(kind.lower()+'-attempt-*')))))
    attempt.mkdir()
    build(kind)
    native = os.name!='nt'
    variant = CANDIDATES[kind]
    frozen = RTL/PARENT/'encoder'
    enc = RTL/variant/'encoder'
    models = Path('/storage1/admin_public_dir/SRAM_Lib_2025') if native else MODELS
    macro = [models/m/'verilog'/(m+'.v') for m in ('RAMSP128X16', 'RAMSP1024X16')]
    if kind == 'PR':
        for case in range(1,13):
            fixtures = SOC/PARENT/'packed_inputs'
            prefix = 'task_%02d_' % case
            addr = (fixtures/(prefix+'addresses.hex')).read_text().splitlines()
            data = (fixtures/(prefix+'payload.hex')).read_text().splitlines()
            words = {int(a,16):v for a,v in zip(addr,data) if int(a,16)<3168}
            assert len(words) == 1+(int(words[0],16)>>4 & 8191)
            (LOCAL/('input_%02d.hex' % case)).write_text('\n'.join(words[i] for i in range(len(words)))+'\n')
        old = attempt/'reference_decode.sv'
        old.write_text((frozen/'decode.sv').read_text().replace('module kwt_lossless_decode ', 'module kwt_lossless_decode_ch '))
        top = 'ch_predictor_tb'
        sources = [old,enc/'decode.sv',macro[0]]
    else:
        sys.path.insert(0,str(ROOT/'scripts/trb_threebank'))
        from fixture import pack
        for case in range(1,13):
            addresses,data=pack(case-1)
            image=dict(zip(addresses,data))
            for name,start,size in [('input',0,3168),('parameter',32768,8512)]:
                (LOCAL/('raw_%s_%02d.hex' % (name,case))).write_text(
                    ''.join('%08x\n'%image[i] for i in range(start,start+size)))
        old = attempt/'reference_core.sv'
        old.write_text((frozen/'kwt_threebank_core.sv').read_text().replace('module kwt_threebank_core ', 'module kwt_threebank_core_ch ').replace(
            '        wire execute=tags[AGE+1].valid;',
            '        wire execute=tags[AGE+1].valid;\n        wire execute_tail=tags[AGE+1].tail;'))
        top = 'ch_accumulator_tb'
        sources = [old,enc/'kwt_threebank_core.sv',enc/'kwt_ffn_requantize.sv',ROOT/'rtl/ffn/kwt_ffn_clock_gate.sv']+macro
    if native:
        sys.path.insert(0,str(ROOT/'scripts/server'))
        from parallel_settings import tool_slot
        binary = attempt/'sim'
        args=['vcs','-full64','-sverilog','+delay_mode_distributed','+notimingcheck','-timescale=1ns/1ps',
              '+define+ARM_UD_MODEL+VERILATOR','-top',top,'-Mdir='+str(attempt/'csrc'),'-o',binary,HERE/(top+'.sv')]
        with tool_slot('vcs'):
            run(args+sources,attempt/'compile.log')
        with tool_slot('simulation'):
            run([binary],attempt/'run.log')
    else:
        binary = attempt/'check.vvp'
        run(['iverilog','-g2012','-DARM_UD_MODEL','-s',top,'-o',binary,HERE/(top+'.sv')]+sources,
            attempt/'compile.log')
        run(['vvp',binary],attempt/'run.log')
    rows=[line for line in (attempt/'run.log').read_text().splitlines() if line.startswith('CH_'+kind+'_PASS')]
    assert len(rows)==12, rows
    (LOCAL/(kind.lower()+'-result.json')).write_text(json.dumps(dict(variant=variant,passed=True,rows=rows,
        evidence=attempt.relative_to(ROOT).as_posix()),indent=2)+'\n')
    print('\n'.join(rows),flush=True)


if __name__=='__main__':
    check(sys.argv[1])
