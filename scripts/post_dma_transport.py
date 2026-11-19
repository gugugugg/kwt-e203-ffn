"""Post-DMA transformations without changing the accepted loading sources."""
import re


def shared_handoff(text):
    prefix = 'joined_' if 'wire idle=!pending&&!joined_rsp_valid' in text else 'cpu_'
    old = 'wire idle=!pending&&!%srsp_valid&&!host_rsp_valid;' % prefix
    new = ('wire idle=!pending&&(!%srsp_valid||%srsp_ready)&&'
           '(!host_rsp_valid||host_rsp_ready);') % (prefix, prefix)
    if old not in text:
        raise ValueError('Shared controller handoff source does not match the frozen controller')
    text = text.replace(old, new, 1)
    return text.replace('kwt_ld_icb_arbiter memory_arbiter(',
                        'kwt_ld_icb_arbiter #(.HANDOFF(1)) memory_arbiter(', 1)


def _span(text, name):
    match = re.search(r'(?:static\s+)?(?:int|void)\s+' + re.escape(name) + r'\([^)]*\)\s*\{', text)
    if match is None:
        raise ValueError('Missing frozen firmware function: ' + name)
    depth, end = 1, match.end()
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return match.start(), end, text[match.start():end]


def flook_driver(text):
    a, b, old_transfer = _span(text, 'ld_transfer')
    output_name = 'transport_output' if 'transport_output(' in text else 'stream_output'
    _, _, output_function = _span(text, output_name)
    output_dma = 'ld_transfer(' in output_function
    cached = 'uintptr_t base=d->base;' in text
    base = 'base' if cached else 'd->base'
    output_arg = 'base' if re.search(r'\(uintptr_t base', output_function) else 'd'
    interleave = 'input+next*32u+8u' in text
    helpers = '''static void ld_prepare(uintptr_t base,const void *buffer,size_t words) {
    fence_io();
    *(volatile uint32_t *)(base+0x40u)=(uint32_t)(uintptr_t)buffer;
    *(volatile uint32_t *)(base+0x44u)=(uint32_t)words;
}
static void ld_launch(uintptr_t base,unsigned direction) {
    fence_io();*(volatile uint32_t *)(base+0x48u)=direction;fence_io();
}
static int ld_join(uintptr_t base) {
    uint32_t status=*(volatile uint32_t *)(base+0x50u);fence_io();
    return (status&4u)?KWU_HW_ERROR:KWU_OK;
}
'''
    text = text[:a] + helpers + text[b:]
    # DMA wrappers are replaced at their original call sites. PIO output stays unchanged.
    names = re.findall(r'static int (\w+)\(', text)
    for name in names:
        a, b, body = _span(text, name)
        if 'ld_transfer(' in body:
            text = text[:a] + text[b:]
    a, b, linear = _span(text, 'kwu_run_linear')
    stage = re.search(r'rc=stage\(context,0,&parameters,&shifts\);\s*if\(rc\)return rc;', linear)
    if stage is None:
        raise ValueError('The frozen linear stage callback changed')
    prefix = linear[:stage.end()] + '\n'
    if cached:
        prefix += '    uintptr_t base=d->base;\n'
    write = (lambda off, value: 'wr_base(base,%s,%s);' % (off, value)) if cached else (
        lambda off, value: 'wr(d,%s,%s);' % (off, value))
    lines = []

    def prepare(pointer, words, indent='    '):
        lines.append(indent + 'ld_prepare(%s,%s,%s);' % (base, pointer, words))

    def launch(direction, indent='    '):
        lines.append(indent + 'ld_launch(%s,%su);' % (base, direction))

    def join(indent='    '):
        lines.append(indent + 'rc=ld_join(%s);if(rc)return rc;' % base)

    def pio(pointer, count, indent='        '):
        # The accepted PIO helper returns void; only the DMA replacement returned int.
        lines.append(indent + '%s(%s,%s,%s);' % (output_name, output_arg, pointer, count))

    lines.append('    ' + write('KIND', '1') + write('ADDR', '0'))
    prepare('parameters', '8704u'); launch(1); prepare('shifts', '64u'); join()
    lines.append('    ' + write('KIND', '5') + write('ADDR', '0'))
    launch(1); prepare('input', '32u'); join()
    lines.append('    rc=wait_state(d,32u);if(rc)return rc;')
    lines.append('    wr(d,KIND,0);wr(d,ADDR,0);wr(d,START_LAYER,1);fence_io();')
    launch(1)
    if interleave:
        prepare('output' if output_dma else 'input+32u', '16u' if output_dma else '8u')
    else:
        prepare('input+32u', '32u')
    join()
    if interleave:
        operations = [('output+row*256u', 32, 2), ('input+next*32u', 8, 1),
                      ('output+row*256u+32u', 64, 2), ('input+next*32u+8u', 8, 1),
                      ('output+row*256u+96u', 64, 2), ('input+next*32u+16u', 8, 1),
                      ('output+row*256u+160u', 64, 2), ('input+next*32u+24u', 8, 1),
                      ('output+row*256u+224u', 32, 2)]
        lines += ['    for(unsigned row=0;row<98;++row) {', '        unsigned next=row+1;']
        for index, (pointer, count, direction) in enumerate(operations):
            if direction == 2 and not output_dma:
                pio(pointer, str(count) + 'u')
                continue
            launch(direction, '        ')
            following = next((op for op in operations[index+1:] if output_dma or op[2] == 1), None)
            if following:
                ptr, words, d = following
                prepare(ptr, str(words//2 if d == 2 else words) + 'u', '        ')
            elif output_dma:
                prepare('output+next*256u', '(next==98)?128u:16u', '        ')
            else:
                lines.append('        if(next<98) {')
                prepare('input+(next+1u)*32u', '8u', '            ')
                lines.append('        }')
            join('        ')
        lines.append('    }')
        if output_dma:
            launch(2); join()
        else:
            pio('output+98u*256u', '256u', '    ')
    else:
        lines += ['    for(unsigned row=0;row<99;++row) {',
                  '        unsigned next=row+1;', '        if(next<99) {']
        launch(1, '            ')
        if output_dma:
            prepare('output+row*256u', '128u', '            ')
        else:
            lines.append('            if(next+1u<99) {')
            prepare('input+(next+1u)*32u', '32u', '                ')
            lines.append('            }')
        join('            ')
        lines.append('        }')
        if output_dma:
            launch(2, '        ')
            lines.append('        if(next+1u<99) {')
            prepare('input+(next+1u)*32u', '32u', '            ')
            lines.append('        } else if(next<99) {')
            prepare('output+next*256u', '128u', '            ')
            lines.append('        }')
            join('        ')
        else:
            pio('output+row*256u', '256u')
        lines.append('    }')
    lines += ['    return wait_state(d,64u);', '}']
    return text[:a] + prefix + '\n'.join(lines) + text[b:]
