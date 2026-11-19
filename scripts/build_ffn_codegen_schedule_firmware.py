"""Build a frozen program with an explicit, complete compiler configuration."""
from pathlib import Path
import json
import shutil
import subprocess
from ffn_codegen_schedule import ROOT, BUILD, load, copy_tree, dump

BASE_FLAGS = ['-march=rv32imac_zicsr_zifencei', '-mabi=ilp32', '-msmall-data-limit=0',
              '-mno-relax', '-ffreestanding', '-fno-builtin', '-Wall', '-Wextra', '-Werror',
              '-nostdlib', '-Wl,--no-relax', '-DKWT_PUBLIC_PLATFORM=1', '-DKWU_PACKED_OUTPUT=1']


def configured_flags(config,macros):
    flags=BASE_FLAGS+['-'+config['optimization']]+list(macros)
    if config['lto']:flags.append('-flto')
    if config['gc_sections']:flags+=['-ffunction-sections','-fdata-sections','-Wl,--gc-sections']
    return flags


def matching_metadata(metadata,request):
    toolchain=request['toolchain']
    return (metadata.get('compiler')==request['compiler'] and
            metadata.get('macros')==request['macros'] and
            metadata.get('compiler_flags')==request['compiler_flags'] and
            metadata.get('compiler_path')==toolchain['compiler_path'] and
            metadata.get('tool_versions')==toolchain['tool_versions'])


def compile_program(program, destination, config, macros):
    program, destination = Path(program), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for tool in ['gcc', 'objcopy', 'objdump']:
        if not shutil.which('riscv-none-elf-' + tool):
            raise RuntimeError('Project cross toolchain is not available: ' + tool)
    tool = shutil.which('riscv-none-elf-gcc')
    versions = {name: subprocess.check_output([shutil.which('riscv-none-elf-' + name), '--version'],
                                            universal_newlines=True).splitlines()[0]
                for name in ['gcc', 'ld', 'objcopy', 'objdump']}
    flags = configured_flags(config,macros)
    sources = ['software/cpu_integration/startup.S', 'software/unified_cpu/main.c', 'driver.c']
    if (program / 'kernels.S').exists():
        sources.append('kernels.S')
    argv = [tool] + flags + ['-Isoftware/unified', '-Tsoftware/cpu_integration/link.ld'] + sources + ['-lgcc', '-o', str((destination / 'firmware.elf').resolve())]
    subprocess.run(argv, cwd=str(program), check=True)
    objcopy = [shutil.which('riscv-none-elf-objcopy'), '-O', 'binary', str(destination / 'firmware.elf'), str(destination / 'firmware.bin')]
    subprocess.run(objcopy, check=True)
    data = (destination / 'firmware.bin').read_bytes()
    image = data.ljust(262144, b'\0')
    (destination / 'firmware_itcm.hex').write_text(''.join('%016x\n' % int.from_bytes(image[i:i+8], 'little') for i in range(0, len(image), 8)))
    disassemble = [shutil.which('riscv-none-elf-objdump'), '-d', str(destination / 'firmware.elf')]
    with (destination / 'disassembly.txt').open('w') as stream:
        subprocess.run(disassemble, stdout=stream, check=True)
    for name in ['driver.c', 'kernels.S']:
        if (program / name).exists():
            shutil.copy2(str(program / name), str(destination / name))
    copy_tree(program, destination / 'input-files')
    dump(destination / 'firmware.json', dict(compiler=config, compiler_flags=flags,
        macros=list(macros),
        compiler_path=tool, tool_versions=versions, compile_and_link_argv=argv,
        objcopy_argv=objcopy, disassembly_argv=disassemble,
        input_files=[p.relative_to(program).as_posix() for p in sorted(program.rglob('*')) if p.is_file()],
        firmware_bytes=len(data), itcm_image_bytes=len(image), mode=3, row_group=1,
        double_buffer=True, source='driver.c', kernels='kernels.S' if 'kernels.S' in sources else None))
    return destination


def request_for(name):
    manifest = load(name)
    parent = manifest['firmware_parent']
    macros = ['-DKWU_ROW_GROUP=1', '-DKWU_DOUBLE_BUFFER=1']
    if not (ROOT / parent['program'] / 'kernels.S').exists():
        macros += ['-DKWU_FFN_UNROLL=8', '-DKWU_BATCH_LOAD=4', '-DKWU_BATCH_OUTPUT=4']
    program=parent['program']
    if 'I' in manifest.get('firmware_changes',[]):
        from interleave_ffn_codegen_schedule import interleave
        destination=BUILD/'generated_programs'/name
        copy_tree(ROOT/program,destination)
        path=destination/'driver.c'
        modified=interleave(path.read_text())
        with path.open('w',newline='\n') as stream:stream.write(modified)
        program=destination.relative_to(ROOT).as_posix()
    toolchain=json.loads((ROOT/'constraints/ffn_codegen_schedule/toolchain.json').read_text())
    return dict(variant=name, compiler=manifest['compiler'], macros=macros, program=program,
                compiler_flags=configured_flags(manifest['compiler'],macros),toolchain=toolchain)


def build(name):
    destination = ROOT / 'build/optimization/firmware' / name
    request = request_for(name)
    metadata = destination / 'firmware.json'
    program = ROOT / request['program']
    if metadata.exists():
        old = json.loads(metadata.read_text())
        snapshot = destination / 'input-files'
        actual = {p.relative_to(program).as_posix(): p.read_bytes() for p in program.rglob('*') if p.is_file()}
        saved = {p.relative_to(snapshot).as_posix(): p.read_bytes() for p in snapshot.rglob('*') if p.is_file()}
        if not matching_metadata(old,request) or actual != saved:
            raise RuntimeError('Firmware source/configuration differs from frozen build: ' + name)
        return destination
    parent_firmware = ROOT / load(name)['firmware_parent']['firmware']
    parent_metadata = json.loads((parent_firmware / 'firmware.json').read_text())
    if matching_metadata(parent_metadata,request):
        snapshot = parent_firmware / 'input-files'
        actual = {p.relative_to(program).as_posix(): p.read_bytes() for p in program.rglob('*') if p.is_file()}
        saved = {p.relative_to(snapshot).as_posix(): p.read_bytes() for p in snapshot.rglob('*') if p.is_file()}
        if actual == saved:
            copy_tree(parent_firmware, destination)
            return destination
    for other in sorted((ROOT/'build/optimization/firmware').glob('ffn_cg_*')):
        if other==destination or not (other/'firmware.json').exists():continue
        value=json.loads((other/'firmware.json').read_text())
        if not matching_metadata(value,request):continue
        actual={p.relative_to(program).as_posix():p.read_bytes() for p in program.rglob('*') if p.is_file()}
        saved={p.relative_to(other/'input-files').as_posix():p.read_bytes() for p in (other/'input-files').rglob('*') if p.is_file()}
        if actual==saved:
            copy_tree(other,destination);return destination
    if shutil.which('riscv-none-elf-gcc'):
        return compile_program(program, destination, request['compiler'], request['macros'])
    import sys
    sys.path.insert(0,str(ROOT/'scripts/server'))
    from request_ffn_codegen_schedule_build import remote_build
    remote_build(request)
    return build(name)


if __name__ == '__main__':
    import sys
    for name in sys.argv[1:]:
        print(build(name))
