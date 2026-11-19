"""Preserve arithmetic and add the approved load-address permutation and ICB DMA frontend."""
import re
from ffn_loading_dma import ROOT,REPORT,load,candidates,copy_tree,dump,prove_bias32

CHANNELS=[('cmd_valid',1,True),('cmd_ready',1,False),('cmd_addr',32,True),('cmd_read',1,True),
          ('cmd_wdata',32,True),('cmd_wmask',4,True),('rsp_valid',1,False),('rsp_ready',1,True),
          ('rsp_rdata',32,False),('rsp_err',1,False)]


def declarations(prefix='ld_',master=True):
    return ',\n'.join('    %s wire %s%s%s'%('output' if outward==master else 'input',
        '' if width==1 else '[%d:0] '%(width-1),prefix,name) for name,width,outward in CHANNELS)


def wires(prefix,address_width=32):
    return '\n'.join('wire %s%s%s;'%('' if width==1 else '[%d:0] '%(width-1),prefix,name)
        for name,original,_ in CHANNELS for width in [address_width if name=='cmd_addr' else original])


def connections(port_prefix,signal_prefix):
    return ',\n'.join('        .%s%s(%s%s)'%(port_prefix,name,signal_prefix,name) for name,_,_ in CHANNELS)


def add_ports(text,module,master=True):
    at=text.index(');',text.index('module '+module))
    return text[:at]+',\n'+declarations(master=master)+'\n'+text[at:]


def encoder_frontend(text):
    end=text.index(');')+2
    header=add_ports(text[:end],'kwt_icb_encoder')
    body=re.sub(r'\bicb_', 'pio_',text[end:])
    body=body.replace('            soft_reset<=0;', '            soft_reset<=0;\n            if(ld_error_sticky)bus_error<=1;',1)
    declarations='\n'+wires('pio_',8)+'\nwire ld_error_sticky,dma_core_load_capacity_ready;\n'
    block='kwt_ld_frontend dma_frontend(\n'
    block+='    .clk(clk),.rst_n(rst_n),.soft_reset(soft_reset),.input_ready(dma_core_load_capacity_ready),.output_ready(core_pair_valid),\n'
    block+=connections('cpu_','icb_')+',\n'+connections('pio_','pio_')+',\n'+connections('ld_','ld_')+',\n    .error_sticky(ld_error_sticky));\n'
    body=body.replace('.load_valid(do_load),.load_ready(core_load_ready),',
                      '.load_valid(do_load),.load_ready(core_load_ready),.load_capacity_ready(dma_core_load_capacity_ready),',1)
    at=body.index('    kwt_encoder core(')
    return header+declarations+body[:at]+block+body[at:]


def dma_load_capacity(text):
    if 'output wire load_ready,load_capacity_ready,' in text:return text
    text=text.replace('output wire load_ready,','output wire load_ready,load_capacity_ready,',1)
    old='assign load_ready=!start_valid&&!layer_start_valid&&'
    at=text.index(old);end=text.index(';',at)
    capacity=text[at+len(old):end].strip()
    return text[:at]+'assign load_capacity_ready='+capacity+';\n    assign load_ready=!start_valid&&!layer_start_valid&&load_capacity_ready'+text[end:]


def tile_layout(text):
    function='''    function automatic [12:0] ld_parameter_address(input [12:0] packed_address);
        begin ld_parameter_address=13'((int'(packed_address)%64)*TILES+int'(packed_address)/64);end
    endfunction
'''
    at=text.index('    always @* begin')
    text=text[:at]+function+text[at:]
    expression="13'(address/LANES)"
    count=text.count(expression)
    if count!=1:raise RuntimeError('Inspect the frozen weight-loading expression before Tile permutation: '+str(count))
    return text.replace(expression,'ld_parameter_address('+expression+')')


def prepare(name):
    manifest=load(name);out=ROOT/'build/optimization/rtl_sources'/name
    copy_tree(ROOT/manifest['parent']['source_snapshot'],out)
    kernel=out/'encoder/kwt_encoder.sv';text=kernel.read_text()
    if manifest['layout']=='tile' and 'ld_parameter_address' not in text:
        text=tile_layout(text)
    if manifest['dma']:
        text=dma_load_capacity(text)
    if text!=kernel.read_text():
        with kernel.open('w',newline='\n') as stream:stream.write(text)
    bus=out/'encoder_bus/kwt_icb_encoder.sv'
    if manifest['dma'] and 'kwt_ld_frontend' not in bus.read_text():
        text=encoder_frontend(bus.read_text())
        with bus.open('w',newline='\n') as stream:stream.write(text)
    if manifest['dma']:
        copy_tree(ROOT/'rtl/loading_dma',out/'encoder')
    if manifest['effective_changes'].get('bias32'):prove_bias32(REPORT/(name+'-bias32-proof.json'))
    dump(out/'loading-configuration.json',manifest)
    return out


def variants():return {name:['PIPE','OUTPUT'] for name in candidates()}


if __name__=='__main__':
    import sys
    for name in sys.argv[1:]:print(prepare(name))
