"""Keep the frozen compiler; change only the requested output mode or descriptor lookahead."""
import json,shutil
from ffn_post_dma import ROOT,BUILD,load,copy_tree
from build_ffn_codegen_schedule_firmware import compile_program,configured_flags,matching_metadata
from build_ffn_loading_dma_firmware import driver


def request_for(name):
    m=load(name);parent=m['parent'];folder=BUILD/'programs'/name
    copy_tree(ROOT/parent['program'],folder)
    path=folder/'driver.c';source=path.read_text()
    if m['output_dma']!=parent['output_dma']:
        source=driver((ROOT/m['pio_program']/'driver.c').read_text(),m['output_dma'])
        already_flook=False
    else:already_flook=parent.get('flook',False)
    if m['flook'] and not already_flook:
        from post_dma_transport import flook_driver
        source=flook_driver(source)
    with path.open('w',newline='\n') as stream:stream.write(source)
    metadata=json.loads((ROOT/parent['firmware']/'firmware.json').read_text())
    macros=metadata.get('macros',['-DKWU_ROW_GROUP=1','-DKWU_DOUBLE_BUFFER=1']+([] if (folder/'kernels.S').exists() else ['-DKWU_FFN_UNROLL=8','-DKWU_BATCH_LOAD=4','-DKWU_BATCH_OUTPUT=4']))
    toolchain=json.loads((ROOT/'constraints/ffn_codegen_schedule/toolchain.json').read_text())
    return dict(variant=name,compiler=m['compiler'],macros=macros,program=folder.relative_to(ROOT).as_posix(),
                compiler_flags=configured_flags(m['compiler'],macros),toolchain=toolchain)


def build(name):
    m=load(name);parent=m['parent'];destination=ROOT/'build/optimization/firmware'/name
    if m['output_dma']==parent['output_dma'] and m['flook']==parent.get('flook',False):
        copy_tree(ROOT/parent['firmware'],destination);return destination
    request=request_for(name);program=ROOT/request['program']
    def matches(folder):
        meta=folder/'firmware.json'
        if not meta.exists() or not matching_metadata(json.loads(meta.read_text()),request):return False
        files=lambda root:{p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
        return files(program)==files(folder/'input-files')
    if (destination/'firmware.json').exists():
        if not matches(destination):raise RuntimeError('Frozen post-DMA firmware differs: '+name)
        return destination
    for other in sorted((ROOT/'build/optimization/firmware').glob('ffn_pd_*')):
        if other!=destination and matches(other):copy_tree(other,destination);return destination
    if shutil.which('riscv-none-elf-gcc'):return compile_program(program,destination,request['compiler'],request['macros'])
    import sys
    sys.path.insert(0,str(ROOT/'scripts/server'))
    from request_ffn_post_dma_build import remote_build
    remote_build(request)
    return build(name)


if __name__=='__main__':
    import sys
    for name in sys.argv[1:]:print(build(name))
