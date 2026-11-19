from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/public_platform'


def build(folder, public):
    folder.mkdir(parents=True, exist_ok=True)
    flags = ['-march=rv32imac_zicsr_zifencei', '-mabi=ilp32', '-msmall-data-limit=0', '-mno-relax',
             '-ffreestanding', '-fno-builtin', '-O2', '-Wall', '-Wextra', '-Werror', '-nostdlib',
             '-Isoftware/kwt', '-Isoftware/kwt_channel', '-Tsoftware/cpu_integration/link.ld',
             '-Wl,--no-relax', '-DKWT_FAST_IO=1']
    if public:
        flags.append('-DKWT_PUBLIC_PLATFORM=1')
    subprocess.run(['riscv-none-elf-gcc'] + flags + ['software/cpu_integration/startup.S',
        'software/kwt_channel/main_timed.c', 'software/kwt_channel/kwt_channel_driver.c', '-lgcc',
        '-o', str(folder / 'firmware.elf')], cwd=ROOT, check=True)
    subprocess.run(['riscv-none-elf-objcopy', '-O', 'binary', str(folder / 'firmware.elf'),
                    str(folder / 'firmware.bin')], cwd=ROOT, check=True)
    binary = (folder / 'firmware.bin').read_bytes()
    padded = binary + bytes((262144 if public else 65536) - len(binary))
    (folder / 'firmware_itcm.hex').write_text(''.join('%016x\n' % int.from_bytes(padded[index:index+8], 'little')
                                                  for index in range(0, len(padded), 8)))
    return binary


def main():
    legacy = build(BUILD / 'legacy_check', False)
    if legacy != (ROOT / 'build/ffn_ablation/D_combined/firmware.bin').read_bytes():
        raise RuntimeError('Default firmware changed during address configuration refactor')
    public = build(BUILD, True)
    record = {'legacy_firmware_byte_identical': True, 'public_firmware_bytes': len(public),
              'public_itcm_image_bytes': 262144, 'accelerator_base': '0x10042000',
              'shared_mailbox_base': '0xA007FF00', 'shared_sram_base': '0xA0000000'}
    (BUILD / 'firmware.json').write_text(json.dumps(record, indent=2))
    print(json.dumps(record))


if __name__ == '__main__':
    main()
