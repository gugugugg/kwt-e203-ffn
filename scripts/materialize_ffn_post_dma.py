"""Apply only the approved delta to a frozen accepted source snapshot."""
from ffn_post_dma import ROOT,REPORT,load,candidates,copy_tree,dump,prove_bias32
from materialize_ffn_loading_dma import add_ports,wires,connections,CHANNELS,tile_layout


def prepare(name):
    manifest=load(name);out=ROOT/'build/optimization/rtl_sources'/name
    copy_tree(ROOT/manifest['parent']['source_snapshot'],out)
    kernel=out/'encoder/kwt_encoder.sv';text=kernel.read_text()
    if 'LAYOUT' in manifest['hardware']:
        if manifest['layout']=='tile':text=tile_layout(text)
        else:
            a=text.index('    function automatic [12:0] ld_parameter_address(')
            b=text.index('endfunction',a)+len('endfunction')
            text=text[:a]+text[b:]
            text=text.replace("ld_parameter_address(13'(address/LANES))","13'(address/LANES)")
    flags=set(manifest['hardware'])&{'AREG','QD4','PM'}
    if flags:
        from post_dma_compute import transform
        text=transform(text,flags)
    with kernel.open('w',newline='\n') as stream:stream.write(text)
    if 'DPIPE' in manifest['hardware']:
        (out/'encoder/kwt_ld_engine.sv').write_bytes((ROOT/'rtl/post_dma/kwt_ld_engine.sv').read_bytes())
    if 'DHAND' in manifest['hardware']:
        (out/'encoder/kwt_ld_icb_arbiter.sv').write_bytes((ROOT/'rtl/post_dma/kwt_ld_icb_arbiter.sv').read_bytes())
    if manifest['effective_changes'].get('bias32'):prove_bias32(REPORT/(name+'-bias32-proof.json'))
    dump(out/'post-dma-configuration.json',manifest)
    return out


def variants():return {name:['PIPE','OUTPUT'] for name in candidates()}


if __name__=='__main__':
    import sys
    for name in sys.argv[1:]:print(prepare(name))
