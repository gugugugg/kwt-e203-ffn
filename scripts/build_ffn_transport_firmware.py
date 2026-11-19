"""Build actual C4/C8/C16 and RVC four-word transport kernels."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
from ffn_transport import ROOT, BUILD, load, dump

FLAGS = ['-march=rv32imac_zicsr_zifencei', '-mabi=ilp32', '-msmall-data-limit=0', '-mno-relax',
         '-ffreestanding', '-fno-builtin', '-O2', '-Wall', '-Wextra', '-Werror', '-nostdlib',
         '-Isoftware/unified', '-Tsoftware/cpu_integration/link.ld', '-Wl,--no-relax',
         '-DKWT_PUBLIC_PLATFORM=1', '-DKWU_PACKED_OUTPUT=1']


def transfer(kind, kernel, cached):
    arg = 'uintptr_t base' if cached else 'const kwu_device *d'
    token = 'base' if cached else 'd'
    width = 4 if kernel == 'asm4' else int(kernel[1:])
    pointer = 'int16_t *output' if kind == 'output' else 'const uint32_t *words'
    text = 'static void transport_%s(%s,%s,size_t count) {\n' % (kind, arg, pointer)
    if kind == 'output':
        text += ' typedef uint32_t packed_word __attribute__((may_alias));\n packed_word *words=(packed_word *)(void *)output;count/=2;\n'
    if kernel == 'asm4':
        text += ' size_t grouped=count&~(size_t)3;\n kwt_transport_%s4(%s+%s,words,grouped);\n size_t i=grouped;\n' % (kind, token, 'PACKED_OUT' if kind == 'output' else 'PACKED_DATA')
    else:
        text += ' size_t i=0;\n for(;i+%d<=count;i+=%d) {\n' % (width, width)
        for i in range(width):
            expr = ('rd_base(%s,PACKED_OUT)' % token if cached else 'rd(d,PACKED_OUT)') if kind == 'output' else 'words[i+%d]' % i
            text += '  uint32_t word%d=%s;\n' % (i, expr)
        for i in range(width):
            text += ('  words[i+%d]=word%d;\n' % (i, i)) if kind == 'output' else ('  wr_base(%s,PACKED_DATA,word%d);\n' % (token, i) if cached else '  wr(d,PACKED_DATA,word%d);\n' % i)
        text += ' }\n'
    if kind == 'output':
        text += ' for(;i<count;++i)words[i]=%s;\n' % ('rd_base(base,PACKED_OUT)' if cached else 'rd(d,PACKED_OUT)')
    else:
        text += ' for(;i<count;++i)%s;\n' % ('wr_base(base,PACKED_DATA,words[i])' if cached else 'wr(d,PACKED_DATA,words[i])')
    return text + ' fence_io();\n}\n'


def assembly():
    text = '.text\n.option push\n.option rvc\n.option norelax\n'
    for kind in ['load', 'output']:
        text += '.align 2\n.globl kwt_transport_%s4\n.type kwt_transport_%s4,@function\nkwt_transport_%s4:\n' % (kind, kind, kind)
        text += ' beqz a2,2f\n slli a6,a2,2\n add a6,a1,a6\n1:\n'
        for i in range(4):
            text += ' c.lw a%d,%d(%s)\n' % (i + 2, 0 if kind == 'output' else i * 4, 'a0' if kind == 'output' else 'a1')
        for i in range(4):
            text += ' c.sw a%d,%d(%s)\n' % (i + 2, i * 4 if kind == 'output' else 0, 'a1' if kind == 'output' else 'a0')
        text += ' c.addi a1,16\n bne a1,a6,1b\n2:\n ret\n.size kwt_transport_%s4,.-kwt_transport_%s4\n' % (kind, kind)
    return text + '.option pop\n'


def driver(settings):
    original = (BUILD / 'frozen_baseline/firmware/driver.c').read_text()
    prefix = original[:original.index('#if defined(KWU_FFN_UNROLL)')]
    standard = original[original.index('static int begin('):original.index('static void stream_input(')]
    cached = settings['base_cached']
    token = 'base' if cached else 'd'
    helpers = '\nstatic uint32_t rd_base(uintptr_t base,unsigned offset){return *(volatile uint32_t *)(base+offset);}\nstatic void wr_base(uintptr_t base,unsigned offset,uint32_t value){*(volatile uint32_t *)(base+offset)=value;}\n' if cached else ''
    helpers += 'extern void kwt_transport_load4(uintptr_t,const uint32_t *,size_t);\nextern void kwt_transport_output4(uintptr_t,uint32_t *,size_t);\n'
    helpers += transfer('load', settings['load_kernel'], cached)
    helpers += transfer('output', settings['output_kernel'], cached)
    body = original[original.index('int kwu_run_linear('):]
    body = body.replace('    load32_ffn(d,1,parameters,8704);load32_ffn(d,5,shifts,64);',
        ('    uintptr_t base=d->base;\n' if cached else '') +
        '    %s; %s;transport_load(%s,parameters,8704);\n    %s; %s;transport_load(%s,shifts,64);' % (
            'wr_base(base,KIND,1)' if cached else 'wr(d,KIND,1)', 'wr_base(base,ADDR,0)' if cached else 'wr(d,ADDR,0)', token,
            'wr_base(base,KIND,5)' if cached else 'wr(d,KIND,5)', 'wr_base(base,ADDR,0)' if cached else 'wr(d,ADDR,0)', token))
    body = body.replace('stream_input(d,', 'transport_load(%s,' % token).replace('stream_output(d,', 'transport_output(%s,' % token)
    # Other control accesses retain the original driver and fences.
    return prefix + standard + helpers + body


def build(name):
    manifest = load(name)
    folder = ROOT / 'build/optimization/firmware' / name
    if (folder / 'firmware.json').exists():
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    settings = manifest['software']
    is_v0 = 'V0' in manifest['hardware']
    if settings.get('frozen'):
        from ffn_transport import copy_tree
        copy_tree(BUILD / 'frozen_baseline/firmware', folder)
        return folder
    if not is_v0:
        from ffn_transport import copy_tree
        for template in sorted((ROOT / 'build/optimization/firmware').glob('ffn_tr_*')):
            metadata = template / 'firmware.json'
            if template == folder or not metadata.exists():
                continue
            previous = json.loads(metadata.read_text())
            if all(previous.get(key) == value for key, value in settings.items()):
                copy_tree(template, folder)
                return folder
    if is_v0:
        source = (BUILD / 'frozen_baseline/firmware/driver.c').read_text()
    else:
        source = driver(settings)
    (folder / 'driver.c').write_text(source)
    (folder / 'kernels.S').write_text(assembly())
    options = ['-DKWU_ROW_GROUP=1']
    if not is_v0:
        options.append('-DKWU_DOUBLE_BUFFER=1')
    else:
        options += ['-DKWU_FFN_UNROLL=8', '-DKWU_BATCH_LOAD=4', '-DKWU_BATCH_OUTPUT=4']
    cmd = ['riscv-none-elf-gcc'] + FLAGS + options + ['software/cpu_integration/startup.S',
        'software/unified_cpu/main.c', str(folder / 'driver.c'), str(folder / 'kernels.S'), '-lgcc', '-o', str(folder / 'firmware.elf')]
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    subprocess.run(['riscv-none-elf-objcopy', '-O', 'binary', str(folder / 'firmware.elf'), str(folder / 'firmware.bin')], check=True)
    data = (folder / 'firmware.bin').read_bytes()
    image = data.ljust(262144, b'\0')
    (folder / 'firmware_itcm.hex').write_text(''.join('%016x\n' % int.from_bytes(image[i:i+8], 'little') for i in range(0, len(image), 8)))
    with (folder / 'disassembly.txt').open('w') as stream:
        subprocess.run(['riscv-none-elf-objdump', '-d', str(folder / 'firmware.elf')], stdout=stream, check=True)
    dump(folder / 'firmware.json', dict(settings, firmware_bytes=len(data), itcm_image_bytes=len(image), mode=3,
                                      row_group=1, double_buffer=not is_v0, compiler_flags=FLAGS,
                                      source='driver.c', kernels='kernels.S', original_driver=is_v0))
    return folder


if __name__ == '__main__':
    for variant in sys.argv[1:]:
        print('TRANSPORT_FIRMWARE_BUILT', variant, build(variant))
