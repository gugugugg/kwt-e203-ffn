"""Check early-response protocol and the unchanged connected SR DMA engine."""
import json
from pathlib import Path
import subprocess

from prepare import ROOT, REPORT, ENDPOINT, replace


def run(command, log):
    with log.open('w') as stream:
        subprocess.check_call(command, cwd=str(ROOT), stdout=stream, stderr=subprocess.STDOUT)


def main():
    out = ROOT / 'build/optimization/ffn_sr_pr1/development'
    out.mkdir(parents=True, exist_ok=True)
    shared = REPORT / ENDPOINT
    tb = ROOT / 'tb'
    memory = tb / 'ffn_loading_dma/shared_memory_model.sv'
    engine = ROOT / 'build/optimization/rtl_sources/ffn_ara_SR/encoder/kwt_ld_engine.sv'
    engine_tb = (tb / 'ffn_tile_pipeline/shared_engine_tb.sv').read_text()
    # Count the real retirement edges for the full no-stall main descriptor.
    engine_tb = replace(engine_tb, 'integer mode=0,cycle=0',
        'integer first_accept=-1,last_rsp=-1,first_pio=-1,last_pio=-1;\n    integer mode=0,cycle=0')
    engine_tb = replace(engine_tb, '            if(mv&&mr) begin', '''            if(transfers==0) begin
                if(mv&&mr&&first_accept<0) first_accept<=cycle;
                if(mrv&&mrr) last_rsp<=cycle;
                if(pv&&pr) begin
                    if(first_pio<0) first_pio<=cycle;
                    last_pio<=cycle;
                end
            end
            if(mv&&mr) begin''')
    engine_tb = replace(engine_tb, '            transfers=transfers+1;', '''            if(transfers==0) begin
                if(last_pio-first_accept!=13056||first_pio-first_accept!=2||last_rsp!=last_pio-1)
                    $fatal(1,"PR1 descriptor cadence differs");
                $display("PR1_REAL_ENGINE main_words=%0d first_accept=%0d last_rsp=%0d first_pio=%0d last_pio=%0d",
                    words,first_accept,last_rsp,first_pio,last_pio);
            end
            transfers=transfers+1;''')
    engine_copy = REPORT / 'shared_engine_tb.sv'
    engine_copy.write_text(engine_tb)
    for label, top, sources in (
        ('endpoint', 'pr1_endpoint_tb', [ROOT/'scripts/sr_pr1/pr1_endpoint_tb.sv']),
        ('engine', 'shared_engine_tb', [engine, tb/'ffn_post_dma/transport_engine_tb.sv', engine_copy]),
    ):
        binary = out / (label + '.vvp')
        run(['iverilog', '-g2012', '-s', top, '-o', str(binary), str(shared), str(memory)] +
            [str(p) for p in sources], REPORT / (label + '-compile.log'))
        run(['vvp', str(binary)], REPORT / (label + '-run.log'))
    run(['yosys','-Q','-T','-p','read_verilog -lib -sv rtl/public_encoder/kwt_shared_sram_sm40.sv; '
         'read_verilog -sv '+shared.relative_to(ROOT).as_posix()+
         '; hierarchy -top kwt_shared_icb_sm40; proc; flatten; opt; scc -expect 0'],
        REPORT / 'combinational-dependencies.log')
    (REPORT / 'local-acceptance.json').write_text(json.dumps(dict(passed=True,
        connected_engine=True, endpoint_protocol=True, combinational_scc=0), indent=2)+'\n')


if __name__ == '__main__':
    main()
