from pathlib import Path
import json
import subprocess
import argparse

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--unpacked',action='store_true')
parser.add_argument('--packed-output',action='store_true')
parser.add_argument('--ffn-unroll',type=int,choices=[1,8],default=1)
parser.add_argument('--output',type=Path)
args=parser.parse_args()
OUT=args.output or ROOT/('build/unified_ablation/unpacked' if args.unpacked else 'build/unified')
OUT.mkdir(parents=True,exist_ok=True)
flags=['-march=rv32imac_zicsr_zifencei','-mabi=ilp32','-msmall-data-limit=0','-mno-relax',
       '-ffreestanding','-fno-builtin','-O2','-Wall','-Wextra','-Werror','-nostdlib',
       '-Isoftware/unified','-Tsoftware/cpu_integration/link.ld','-Wl,--no-relax',
       '-DKWT_PUBLIC_PLATFORM=1']
if args.unpacked:flags+=['-DKWU_UNPACKED_LOAD=1']
if args.packed_output:flags+=['-DKWU_PACKED_OUTPUT=1']
if args.ffn_unroll==8:flags+=['-DKWU_FFN_UNROLL=8']
subprocess.run(['riscv-none-elf-gcc']+flags+[
    'software/cpu_integration/startup.S','software/unified_cpu/main.c',
    'software/unified/kwt_unified_driver.c','-lgcc','-o',str(OUT/'firmware.elf')],
    cwd=ROOT,check=True)
subprocess.run(['riscv-none-elf-objcopy','-O','binary',str(OUT/'firmware.elf'),
                str(OUT/'firmware.bin')],check=True)
binary=(OUT/'firmware.bin').read_bytes()
image=binary.ljust(262144,b'\0')
(OUT/'firmware_itcm.hex').write_text(''.join(
    '%016x\n'%int.from_bytes(image[i:i+8],'little') for i in range(0,len(image),8)))
record={'firmware_bytes':len(binary),'itcm_image_bytes':len(image),
        'ffn_unroll':args.ffn_unroll,
        'load_protocol':'unpacked16' if args.unpacked else 'packed32',
        'output_protocol':'packed32' if args.packed_output else 'single16',
        'modes':{'encoder':0,'linear':1},'accelerator_base':'0x10042000',
        'shared_sram_bytes':524288,'mailbox_base':'0xA007FF00'}
(OUT/'firmware.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record))
