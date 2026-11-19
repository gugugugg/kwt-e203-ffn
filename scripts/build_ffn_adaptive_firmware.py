"""Build the recorded four-word transfer experiment with the original CPU flags."""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import sys
from ffn_adaptive import ROOT,load,dump,MANIFESTS
parser=argparse.ArgumentParser();parser.add_argument('variant',nargs='?');parser.add_argument('--templates',action='store_true');args=parser.parse_args()
if args.templates:
    for unroll in [False,True]:
        for batch_load,batch_output in [(True,False),(False,True),(True,True)]:
            name='ffn_adp_template_u%d_load%d_out%d'%(unroll,batch_load,batch_output)
            dump(MANIFESTS/(name+'.json'),dict(variant=name,purpose='firmware_template',features=dict(unroll=unroll),
                changes=dict(batch_load=batch_load,batch_output=batch_output),parent={}))
            subprocess.run([sys.executable,__file__,name],cwd=ROOT,check=True)
    sys.exit(0)
m=load(args.variant);c=m['changes'];out=ROOT/'build/optimization/firmware'/args.variant
out.mkdir(parents=True,exist_ok=True)
if not (c.get('batch_load') or c.get('batch_output')):
    from ffn_adaptive import copy_tree
    copy_tree(ROOT/m['parent']['firmware'],out)
else:
    flags=['-march=rv32imac_zicsr_zifencei','-mabi=ilp32','-msmall-data-limit=0','-mno-relax',
           '-ffreestanding','-fno-builtin','-O2','-Wall','-Wextra','-Werror','-nostdlib',
           '-Isoftware/unified','-Tsoftware/cpu_integration/link.ld','-Wl,--no-relax',
           '-DKWT_PUBLIC_PLATFORM=1','-DKWU_PACKED_OUTPUT=1']
    if m['features']['unroll']:flags.append('-DKWU_FFN_UNROLL=8')
    if c.get('batch_load'):flags.append('-DKWU_BATCH_LOAD=4')
    if c.get('batch_output'):flags.append('-DKWU_BATCH_OUTPUT=4')
    subprocess.run(['riscv-none-elf-gcc']+flags+['software/cpu_integration/startup.S','software/unified_cpu/main.c',
        'software/ffn_adaptive/kwt_unified_driver.c','-lgcc','-o',str(out/'firmware.elf')],cwd=ROOT,check=True)
    subprocess.run(['riscv-none-elf-objcopy','-O','binary',str(out/'firmware.elf'),str(out/'firmware.bin')],check=True)
    binary=(out/'firmware.bin').read_bytes();image=binary.ljust(262144,b'\0')
    (out/'firmware_itcm.hex').write_text(''.join('%016x\n'%int.from_bytes(image[i:i+8],'little') for i in range(0,len(image),8)))
    (out/'firmware.json').write_text(json.dumps(dict(firmware_bytes=len(binary),itcm_image_bytes=len(image),
        load_protocol='packed32',output_protocol='packed32',ffn_unroll=8 if m['features']['unroll'] else 1,
        batch_load=bool(c.get('batch_load')),batch_output=bool(c.get('batch_output'))),indent=2))
    shutil.copy2(ROOT/'software/ffn_adaptive/kwt_unified_driver.c',out/'driver.c')
    subprocess.run(['riscv-none-elf-objdump','-d',str(out/'firmware.elf')],stdout=(out/'disassembly.txt').open('w'),check=True)
print(out)
