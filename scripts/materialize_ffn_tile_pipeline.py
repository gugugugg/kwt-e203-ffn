"""Apply fifth-round deltas to the immutable accepted source snapshot."""
from ffn_tile_pipeline import ROOT, REPORT, load, candidates, copy_tree, dump, prove_bias32
from materialize_ffn_loading_dma import add_ports, wires, connections, CHANNELS


def prepare(name):
    manifest = load(name)
    out = ROOT / 'build/optimization/rtl_sources' / name
    copy_tree(ROOT / manifest['parent']['source_snapshot'], out)
    from tile_pipeline_compute import transform, adapt_bus_trace
    kernel = out / 'encoder/kwt_encoder.sv'
    kernel.write_text(transform(kernel.read_text(), manifest['hardware']))
    bus = out / 'encoder_bus/kwt_icb_encoder.sv'
    bus.write_text(adapt_bus_trace(bus.read_text()))
    if manifest['effective_changes'].get('bias32'):
        prove_bias32(REPORT / (name + '-bias32-proof.json'))
    dump(out / 'tile-pipeline-configuration.json', manifest)
    return out


def variants():
    return {name: ['PIPE', 'OUTPUT'] for name in candidates()}


if __name__ == '__main__':
    import sys
    for name in sys.argv[1:]:
        print(prepare(name))
