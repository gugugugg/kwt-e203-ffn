"""Add study-only event observation to copies of the frozen IR testbenches."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/optimization/ffn_taskflow_study'
REPORT = ROOT / 'reports/optimization/ffn_taskflow_study'
SOURCE = ROOT / 'build/optimization/rtl_sources/ffn_lp_IR'
SOC = ROOT / 'build/optimization/complete_soc/ffn_lp_IR'


def fields(controller, native):
    core = controller + '.core'
    frontend = controller + '.dma_frontend'
    engine = frontend + '.loading_dma'
    queue = core + '.output_queue'
    values = [('cycle', 'cycles-start_cycle' if native else 'tf_cycle'),
              ('state', core + '.state'), ('row', core + '.row'), ('tile', core + '.tile'),
              ('inner', core + '.inner'), ('lane', core + '.lane'), ('chunk', core + '.chunk'),
              ('emit_row', core + '.emit_row'), ('item', core + '.item'),
              ('input_count', core + '.input_count'), ('parameter_count', core + '.parameter_count'),
              ('shift_count', core + '.shift_count'), ('seed_ready', core + '.ap_er_next_seed_ready'),
              ('soft_reset', controller + '.soft_reset'), ('done', controller + '.done_sticky'),
              ('load_kind', controller + '.load_kind'), ('load_address', controller + '.load_address'),
              ('pack_pending', controller + '.pack_pending'), ('stored_rsp_valid', controller + '.stored_rsp_valid'),
              ('csr_rsp_valid', frontend + '.csr_rsp_valid'),
              ('core_start', controller + '.do_start'), ('core_layer_start', controller + '.do_layer'),
              ('core_load', controller + '.do_load'), ('core_load_data', controller + '.core_load_data'),
              ('core_load_pair', controller + '.packed_load&&(' + controller + '.load_kind!=0)&&(' + controller + '.load_kind!=5)'),
              ('fifo_count', queue + '.fifo_count'), ('row0_count', queue + '.row0_count'),
              ('row1_count', queue + '.row1_count'), ('held_count', queue + '.held_count'),
              ('pending_count', queue + '.pending_count'), ('pending_row1', queue + '.pending_row1'),
              ('fifo_read', queue + '.fifo_read'), ('fifo_write', queue + '.fifo_write'),
              ('row0_read', queue + '.row0_read'), ('row0_write', queue + '.row0_write'),
              ('row1_read', queue + '.row1_read'), ('row1_write', queue + '.row1_write'),
              ('read0', queue + '.read0'), ('read1', queue + '.read1'), ('drain0', queue + '.drain0'),
              ('row0_push', queue + '.row0_push'), ('row1_push', queue + '.row1_push'),
              ('pop_count', core + '.pop_count'), ('quant', core + '.jp_quant_commit'),
              ('mac_mask', core + '.jp_mac_mask'), ('seed_mask', core + '.jp_seed_mask'),
              ('out_low', core + '.out_data'), ('out_high', core + '.out_high')]
    for label, stem, signals in [
        ('cpu', controller + '.icb_', ['cmd_valid', 'cmd_ready', 'cmd_read', 'cmd_addr', 'cmd_wdata', 'cmd_wmask', 'rsp_valid', 'rsp_ready', 'rsp_rdata']),
        ('pio', controller + '.pio_', ['cmd_valid', 'cmd_ready', 'cmd_read', 'cmd_addr', 'cmd_wdata', 'rsp_valid', 'rsp_ready']),
        ('mem', controller + '.ld_', ['cmd_valid', 'cmd_ready', 'cmd_read', 'cmd_addr', 'cmd_wdata', 'rsp_valid', 'rsp_ready', 'rsp_rdata'])]:
        values.extend((label + '_' + signal, stem + signal) for signal in signals)
    values.extend(('dma_' + name, engine + '.' + name) for name in [
        'pd_active', 'output_transfer', 'address', 'source_remaining', 'dest_remaining',
        'pd_count', 'pd_valid', 'pd_write', 'pd_read', 'pd_source_slot', 'pd_source_pending', 'pd_dest_pending', 'done'])
    values.extend(('arb_' + name, frontend + '.core_arbiter.' + name)
                  for name in ['active', 'owner', 'prefer_b', 'held_valid', 'held_owner'])
    for bank in range(2):
        stem = core + '.ap_input_rows[%d].' % bank
        values.extend(('in%d_' % bank + key, stem + expr) for key, expr in [
            ('read', 'read_enable'), ('write', 'write_enable'), ('address', 'memory_addr')])
    for bank in range(3):
        stem = queue + '.row_stash[%d].' % bank
        values.extend(('out%d_' % bank + key, stem + key) for key in ['en', 'we', 'address'])
    if native:
        for label, stem, names in [
            ('host', 'dut.shared_memory.host_', ['cmd_valid', 'cmd_ready', 'cmd_read', 'cmd_addr', 'cmd_wdata', 'cmd_wmask', 'rsp_valid', 'rsp_ready']),
            ('shared_cpu', 'dut.shared_memory.cpu_', ['cmd_valid', 'cmd_ready', 'cmd_read', 'cmd_addr', 'cmd_wdata', 'rsp_valid', 'rsp_ready'])]:
            values.extend((label + '_' + name, stem + name) for name in names)
        values.extend((name, 'dut.shared_memory.' + expr) for name, expr in [
            ('physical_accept', 'physical_accept'), ('physical_write', 'physical_write'),
            ('physical_address', 'live_addr'), ('physical_wdata', 'live_wdata'),
            ('shared_pending', 'pending'), ('shared_rsp_valid', 'joined_rsp_valid'),
            ('shared_host_rsp_valid', 'host_rsp_valid')])
    return values


def observer(controller, native):
    values = fields(controller, native)
    window = 'activity_window' if native else 'active'
    header = ','.join(name for name, unused in values)
    return '''
    integer tf_fd,tf_cycle=0;
    string tf_trace_path;
    initial begin
        if(!$value$plusargs("TF_TRACE=%s",tf_trace_path))$fatal(1,"TASKFLOW_TRACE_PATH_REQUIRED");
        tf_fd=$fopen(tf_trace_path,"w");
        $fwrite(tf_fd,"HEADER\\n");
    end
    always @(posedge clk) begin
        tf_cycle<=tf_cycle+1;
        if(WINDOW)$fwrite(tf_fd,"FORMAT\\n",EXPRESSIONS);
    end
    final $fclose(tf_fd);
'''.replace('HEADER', header).replace('WINDOW', window).replace(
        'FORMAT', ','.join(['%h'] * len(values))).replace('EXPRESSIONS', ','.join(expr for unused, expr in values))


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    local = (ROOT / 'build/optimization/rtl/ffn_lp_IR/loading_dma_tb.sv').read_text()
    local = local.replace('layer<12', 'layer<1')
    at = local.rfind('endmodule')
    local = local[:at] + observer('dut', False) + local[at:]
    (OUT / 'local_observed_tb.sv').write_text(local)
    native = (SOC / 'complete_soc_tb.sv').read_text()
    controller = 'dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller'
    at = native.rfind('endmodule')
    native = native[:at] + observer(controller, True) + native[at:]
    (OUT / 'native_observed_tb.sv').write_text(native)
    original = (SOC / 'files.f').read_text()
    original = original.replace('build/optimization/complete_soc/ffn_lp_IR/complete_soc_tb.sv',
                                'build/optimization/ffn_taskflow_study/native_observed_tb.sv')
    (OUT / 'native_observed_files.f').write_text(original)
    schema = dict(local=[name for name, unused in fields('dut', False)],
                  native=[name for name, unused in fields(controller, True)],
                  encoding='CSV; all values hexadecimal; unknown X/Z retained',
                  scope='External observation only; frozen hardware and firmware unchanged')
    (REPORT / 'trace-schema.json').write_text(json.dumps(schema, indent=2))


if __name__ == '__main__':
    prepare()
