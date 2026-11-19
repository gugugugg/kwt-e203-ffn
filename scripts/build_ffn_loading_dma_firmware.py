"""Preserve the selected compiler and replace only the selected linear transfer helpers."""
import json
from ffn_loading_dma import ROOT,BUILD,load,copy_tree,dump
from build_ffn_codegen_schedule_firmware import compile_program,configured_flags,matching_metadata


def function_span(text,name):
    import re
    match=re.search(r'static void '+name+r'\([^)]*\)\s*\{',text)
    if not match:raise RuntimeError('Frozen transfer helper is not recognized: '+name)
    at=match.end();depth=1;end=at
    while depth:
        depth+=int(text[end]=='{')-int(text[end]=='}');end+=1
    return match.start(),end,text[match.start():match.end()-1]


def driver(original,output_dma):
    helper='''static int ld_transfer(uintptr_t base,const void *buffer,size_t words,unsigned direction) {
    fence_io();
    *(volatile uint32_t *)(base+0x40u)=(uint32_t)(uintptr_t)buffer;
    *(volatile uint32_t *)(base+0x44u)=(uint32_t)words;
    fence_io();*(volatile uint32_t *)(base+0x48u)=direction;fence_io();
    uint32_t status=*(volatile uint32_t *)(base+0x50u);fence_io();
    return (status&4u)?KWU_HW_ERROR:KWU_OK;
}
'''
    at=original.index('static int wait_state(');text=original[:at]+helper+original[at:]
    modern='static void transport_load(' in text
    names=['transport_load'] if modern else ['load32_ffn','stream_input']
    if output_dma:names.append('transport_output' if modern else 'stream_output')
    changed=[]
    for name in names:
        a,b,signature=function_span(text,name)
        cached='uintptr_t base' in signature
        base='base' if cached else 'd->base'
        if name=='load32_ffn':body='    wr(d,KIND,kind);wr(d,ADDR,0);\n'
        else:body=''
        if name.endswith('output'):
            body+='    return ld_transfer(%s,output,count/2u,2u);\n'%base
        else:body+='    return ld_transfer(%s,words,count,1u);\n'%base
        text=text[:a]+signature.replace('static void ','static int ',1)+'{\n'+body+'}\n'+text[b:]
        changed.append(name)
    at=text.index('int kwu_run_linear(')
    prefix,body=text[:at],text[at:]
    import re
    for name in changed:
        body=re.sub(r'\b'+name+r'\(([^;]*)\);',lambda m:'{rc='+name+'('+m.group(1)+');if(rc)return rc;}',body)
    text=prefix+body
    if text.count('rd_base(')==1:
        start=text.index('static uint32_t rd_base(');end=text.index('}',start)+1;text=text[:start]+text[end:]
    return text


def request_for(name):
    manifest=load(name);parent=manifest['parent'];folder=BUILD/'programs'/name
    copy_tree(ROOT/parent['program'],folder)
    if manifest['dma']:
        p=folder/'driver.c'
        # Each DMA configuration is derived from the same frozen PIO program, not another DMA helper.
        frozen=ROOT/manifest.get('frozen_program',parent['program'])/'driver.c'
        source=frozen.read_text()
        if 'static int ld_transfer(' in source:
            source=(ROOT/manifest['pio_program']/'driver.c').read_text()
        text=driver(source,manifest['output_dma'])
        with p.open('w',newline='\n') as stream:stream.write(text)
    metadata=json.loads((ROOT/parent['firmware']/'firmware.json').read_text())
    macros=metadata.get('macros',['-DKWU_ROW_GROUP=1','-DKWU_DOUBLE_BUFFER=1']+([] if (folder/'kernels.S').exists() else ['-DKWU_FFN_UNROLL=8','-DKWU_BATCH_LOAD=4','-DKWU_BATCH_OUTPUT=4']))
    toolchain=json.loads((ROOT/'constraints/ffn_codegen_schedule/toolchain.json').read_text())
    return dict(variant=name,compiler=manifest['compiler'],macros=macros,program=folder.relative_to(ROOT).as_posix(),
                compiler_flags=configured_flags(manifest['compiler'],macros),toolchain=toolchain)


def build(name):
    manifest=load(name);destination=ROOT/'build/optimization/firmware'/name
    if not manifest['dma']:
        copy_tree(ROOT/manifest['parent']['firmware'],destination);return destination
    request=request_for(name);program=ROOT/request['program'];metadata=destination/'firmware.json'
    def matches(folder):
        if not (folder/'firmware.json').exists():return False
        data=json.loads((folder/'firmware.json').read_text())
        if not matching_metadata(data,request):return False
        files=lambda root:{p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
        return files(program)==files(folder/'input-files')
    if metadata.exists():
        if not matches(destination):raise RuntimeError('Frozen DMA program differs: '+name)
        return destination
    for folder in sorted((ROOT/'build/optimization/firmware').glob('ffn_ld_*')):
        if folder!=destination and matches(folder):copy_tree(folder,destination);return destination
    import shutil
    if shutil.which('riscv-none-elf-gcc'):return compile_program(program,destination,request['compiler'],request['macros'])
    import sys
    sys.path.insert(0,str(ROOT/'scripts/server'))
    from request_ffn_loading_dma_build import remote_build
    remote_build(request)
    return build(name)


if __name__=='__main__':
    import sys
    for name in sys.argv[1:]:print(build(name))
