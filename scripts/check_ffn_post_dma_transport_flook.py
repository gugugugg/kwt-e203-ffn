"""Compile actual FLOOK firmware and exercise both modes through a normal-use MMIO model."""
from pathlib import Path
from datetime import datetime
import json
import re
import subprocess
from post_dma_transport import flook_driver
from build_ffn_loading_dma_firmware import driver as dma_driver
from interleave_ffn_codegen_schedule import interleave

ROOT=Path(__file__).resolve().parents[1]


def intercept(text):
    text=text.replace('__asm__ volatile("fence iorw,iorw" ::: "memory");','transport_fence();')
    text=re.sub(r'\*\(volatile uint32_t \*\)\((?:base\+|d->base\+)([^)]+)\)\s*=\s*([^;]+);',
                r'transport_write(\1,\2);',text)
    text=re.sub(r'\*\(volatile uint32_t \*\)\((?:base\+|d->base\+)([^)]+)\)',r'transport_read(\1)',text)
    return text


def main():
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    out=ROOT/'build/optimization/ffn_post_dma/development'/('flook-'+stamp)
    report=ROOT/'reports/optimization/ffn_post_dma/development'/('flook-'+stamp)
    out.mkdir(parents=True);report.mkdir(parents=True)
    def run(name,cmd):
        with (report/(name+'.log')).open('w') as stream:
            subprocess.run([str(x) for x in cmd],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        return (report/(name+'.log')).read_text()
    header=ROOT/'software/unified'
    modern=(ROOT/'build/optimization/firmware/ffn_tr_HW_F/driver.c').read_text()
    legacy=(ROOT/'build/optimization/ffn_loading_dma/development_programs/B/driver.c').read_text()
    harness=(ROOT/'tb/ffn_post_dma/transport_flook_harness.c').read_text()
    results=[]
    for family,source in [('cached',modern),('legacy',legacy)]:
        for segmented in [False,True]:
            for output_dma in [False,True]:
                label='%s_%s_%s'%(family,'interleave' if segmented else 'row','dmaout' if output_dma else 'pioout')
                loaded=dma_driver(interleave(source) if segmented else source,output_dma)
                modified=flook_driver(loaded)
                actual=out/(label+'.c');actual.write_text(modified)
                flags=['-march=rv32imac_zicsr_zifencei','-mabi=ilp32','-msmall-data-limit=0','-mno-relax',
                       '-ffreestanding','-fno-builtin','-Wall','-Wextra','-Werror','-O2',
                       '-DKWU_ROW_GROUP=1','-DKWU_DOUBLE_BUFFER=1','-DKWU_PACKED_OUTPUT=1',
                       '-DKWU_FFN_UNROLL=8','-DKWU_BATCH_LOAD=4','-DKWU_BATCH_OUTPUT=4','-I'+str(header)]
                run(label+'-riscv',['riscv-none-elf-gcc']+flags+['-c',actual,'-o',out/(label+'.o')])
                for variant,program in [('baseline',loaded),('flook',modified)]:
                    native=out/(label+'-'+variant+'.c');native.write_text(harness.replace('/* DRIVER */',intercept(program)))
                    exe=out/(label+'-'+variant+'.exe')
                    run(label+'-'+variant+'-compile',['gcc','-std=c11','-O2','-DKWU_ROW_GROUP=1','-DKWU_DOUBLE_BUFFER=1',
                        '-DKWU_PACKED_OUTPUT=1','-DKWU_FFN_UNROLL=8','-DKWU_BATCH_LOAD=4','-DKWU_BATCH_OUTPUT=4','-I'+str(header),native,'-o',exe])
                    log=run(label+'-'+variant,[exe])
                    match=re.search(r'busy_descriptor_writes=(\d+)',log)
                    if 'POST_DMA_FLOOK_PASS' not in log or match is None:raise RuntimeError(log)
                    writes=int(match.group(1))
                    if (variant=='flook')!=(writes>0):raise RuntimeError('Lookahead busy writes did not match '+variant)
                    results.append(dict(configuration=label,variant=variant,log=log.strip()))
    result=dict(passed=True,scope='RISC-V compilation and host-executed original driver with MMIO endpoint model; two consecutive 99-row tasks',configurations=results)
    (report/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)


if __name__=='__main__':main()
