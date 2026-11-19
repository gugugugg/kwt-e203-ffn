from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/public_encoder'
OUT.mkdir(parents=True, exist_ok=True)
flags = ['-march=rv32imac_zicsr_zifencei','-mabi=ilp32','-msmall-data-limit=0','-mno-relax',
         '-ffreestanding','-fno-builtin','-O2','-Wall','-Wextra','-Werror','-nostdlib',
         '-Isoftware/encoder','-Tsoftware/cpu_integration/link.ld','-Wl,--no-relax',
         '-DKWT_PUBLIC_PLATFORM=1']
subprocess.run(['riscv-none-elf-gcc'] + flags + ['software/cpu_integration/startup.S',
    'software/encoder_cpu/main.c','software/encoder/kwt_encoder_driver.c','-lgcc',
    '-o',str(OUT/'firmware.elf')],cwd=ROOT,check=True)
subprocess.run(['riscv-none-elf-objcopy','-O','binary',str(OUT/'firmware.elf'),str(OUT/'firmware.bin')],check=True)
binary=(OUT/'firmware.bin').read_bytes()
padded=binary+bytes(262144-len(binary))
(OUT/'firmware_itcm.hex').write_text(''.join('%016x\n'%int.from_bytes(padded[i:i+8],'little') for i in range(0,len(padded),8)))
(OUT/'firmware_itcm64.hex').write_text((OUT/'firmware_itcm.hex').read_text())
record={'firmware_bytes':len(binary),'itcm_image_bytes':262144,'accelerator':'0x10042000',
        'mailbox':'0xA007FF00','shared_sram_bytes':524288,'layers':12}
(OUT/'firmware.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record))
