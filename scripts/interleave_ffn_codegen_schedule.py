"""The approved deterministic single-row upload/output interleave."""


def interleave(text):
    start=text.index('    for(unsigned row=0;row<99;row+=KWU_ROW_GROUP)')
    end=text.index('    return wait_state(d,64u);',start)
    if 'static void transport_load(' in text:
        token='base' if 'uintptr_t base=d->base;' in text else 'd'
        upload='transport_load';output='transport_output'
    else:
        token='d';upload='stream_input';output='stream_output'
    loop='''    for(unsigned row=0;row<99;++row) {
        unsigned next=row+1;
        if(next<99) {
            %s(%s,output+row*256u,32u);
            %s(%s,input+next*32u,8u);
            %s(%s,output+row*256u+32u,64u);
            %s(%s,input+next*32u+8u,8u);
            %s(%s,output+row*256u+96u,64u);
            %s(%s,input+next*32u+16u,8u);
            %s(%s,output+row*256u+160u,64u);
            %s(%s,input+next*32u+24u,8u);
            %s(%s,output+row*256u+224u,32u);
        } else %s(%s,output+row*256u,256u);
    }
''' % tuple(v for function in [output,upload,output,upload,output,upload,output,upload,output,output] for v in [function,token])
    return text[:start]+loop+text[end:]
