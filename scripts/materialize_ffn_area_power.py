"""Apply C, R, G in order to the immutable accepted fifth-round source."""
from ffn_area_power import ROOT, REPORT, load, candidates, copy_tree, dump, prove_bias32
from materialize_ffn_loading_dma import add_ports, wires, connections, CHANNELS


def prepare(name):
    manifest = load(name)
    out = ROOT / 'build/optimization/rtl_sources' / name
    copy_tree(ROOT / manifest['parent']['source_snapshot'], out)
    kernel = out / 'encoder/kwt_encoder.sv'
    bus = out / 'encoder_bus/kwt_icb_encoder.sv'
    core_text, bus_text = kernel.read_text(), bus.read_text()
    hardware = manifest['hardware']
    if 'C' in hardware:
        from area_power_compute import transform_core
        core_text = transform_core(core_text)
    if 'R' in hardware:
        from area_power_input import transform_core, transform_wrapper
        core_text, bus_text = transform_core(core_text), transform_wrapper(bus_text)
    if 'G' in hardware:
        from area_power_weights import transform_core
        core_text = transform_core(core_text)
    kernel.write_text(core_text)
    bus.write_text(bus_text)
    if manifest['effective_changes'].get('bias32'):
        prove_bias32(REPORT / (name + '-bias32-proof.json'))
    dump(out / 'area-power-configuration.json', manifest)
    return out


def variants():
    return {name: ['PIPE', 'OUTPUT'] for name in candidates()}


if __name__ == '__main__':
    import sys
    for name in sys.argv[1:]:
        print(prepare(name))
