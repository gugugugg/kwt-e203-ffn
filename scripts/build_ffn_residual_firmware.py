"""Build matched stream firmware templates with the established compiler and flags."""
from pathlib import Path
import itertools,json,subprocess,shutil
ROOT=Path(__file__).resolve().parents[1]
flags=['-march=rv32imac_zicsr_zifencei','-mabi=ilp32','-msmall-data-limit=0','-mno-relax',
 '-ffreestanding','-fno-builtin','-O2','-Wall','-Wextra','-Werror','-nostdlib',
 '-Isoftware/unified','-Tsoftware/cpu_integration/link.ld','-Wl,--no-relax','-DKWT_PUBLIC_PLATFORM=1','-DKWU_PACKED_OUTPUT=1']
for group,double,unroll,load,out in itertools.product([1,2,4],[0,1],[0,1],[0,1],[0,1]):
 name='ffn_res_template_r%d_d%d_u%d_l%d_o%d'%(group,double,unroll,load,out)
 folder=ROOT/'build/optimization/firmware'/name;folder.mkdir(parents=True,exist_ok=True)
 options=['-DKWU_ROW_GROUP=%d'%group]
 if double:options.append('-DKWU_DOUBLE_BUFFER=1')
 if unroll:options.append('-DKWU_FFN_UNROLL=8')
 if load:options.append('-DKWU_BATCH_LOAD=4')
 if out:options.append('-DKWU_BATCH_OUTPUT=4')
 subprocess.run(['riscv-none-elf-gcc']+flags+options+['software/cpu_integration/startup.S','software/unified_cpu/main.c','software/ffn_residual/kwt_unified_driver.c','-lgcc','-o',str(folder/'firmware.elf')],cwd=ROOT,check=True)
 subprocess.run(['riscv-none-elf-objcopy','-O','binary',str(folder/'firmware.elf'),str(folder/'firmware.bin')],check=True)
 data=(folder/'firmware.bin').read_bytes();image=data.ljust(262144,b'\0')
 (folder/'firmware_itcm.hex').write_text(''.join('%016x\n'%int.from_bytes(image[i:i+8],'little') for i in range(0,len(image),8)))
 (folder/'firmware.json').write_text(json.dumps(dict(firmware_bytes=len(data),itcm_image_bytes=len(image),row_group=group,double_buffer=bool(double),unroll=bool(unroll),batch_load=bool(load),batch_output=bool(out),mode=3),indent=2))
 shutil.copy2(ROOT/'software/ffn_residual/kwt_unified_driver.c',folder/'driver.c')
 with (folder/'disassembly.txt').open('w') as f:subprocess.run(['riscv-none-elf-objdump','-d',str(folder/'firmware.elf')],stdout=f,check=True)
print('STREAM_FIRMWARE_TEMPLATES_READY',48)
