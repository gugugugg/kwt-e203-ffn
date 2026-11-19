"""Collect one observation-only case from the accepted INT16 System Bus baseline."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/trb_sysbus32'))
from native import DEST, SOC, job, preflight

REPORT = ROOT / 'reports/optimization/ffn_sysbus32_3k/baseline-observation'
MAIN = 'dut.soc.u_e203_subsys_main'


def main():
    preflight()
    REPORT.mkdir(parents=True)
    frozen = SOC / 'complete_soc_tb.sv'
    original = frozen.read_text(encoding='utf-8')
    insert = r'''
    integer observer;
    initial observer = $fopen("reports/optimization/ffn_sysbus32_3k/baseline-observation/events.csv", "w");
    always @(posedge system_clk) if (system_reset_n && activity_window) begin
        $fdisplay(observer, "%0d,%b,%b,%b,%b,%h,%b,%b,%b,%h,%b,%b,%b,%h,%b,%b,%h,%b,%b,%b,%h,%b,%b,%b,%b,%b,%b,%h,%b,%b,%b",
            cycles-start_cycle,
            @MAIN@.mem_icb_cmd_valid,@MAIN@.mem_icb_cmd_ready,@MAIN@.mem_icb_cmd_read,
            @MAIN@.mem_icb_rsp_valid,@MAIN@.mem_icb_cmd_addr,
            host_cmd_valid,host_cmd_ready,host_cmd_read,host_cmd_addr,host_rsp_valid,
            @MAIN@.ld_cmd_valid,@MAIN@.ld_cmd_read,@MAIN@.ld_cmd_addr,@MAIN@.ld_cmd_ready,@MAIN@.ld_rsp_valid,
            @MAIN@.merged_cmd_addr,@MAIN@.merged_cmd_valid,@MAIN@.merged_cmd_ready,@MAIN@.merged_cmd_read,
            @MAIN@.sysmem_icb_cmd_addr,@MAIN@.sysmem_icb_cmd_valid,@MAIN@.sysmem_icb_cmd_ready,
            @MAIN@.sysmem_icb_rsp_valid,@MAIN@.sysmem_icb_rsp_ready,
            dut.shared_memory.memory.en,dut.shared_memory.memory.we,dut.shared_memory.memory.addr,
            @MAIN@.merged_rsp_valid,@MAIN@.merged_rsp_ready,
            @MAIN@.sysmem_icb_cmd_read);
    end
'''.replace('@MAIN@', MAIN)
    before, marker, after = original.rpartition('endmodule')
    assert marker and not after.strip()
    bench = REPORT / frozen.name
    bench.write_text(before + insert + marker + after, encoding='utf-8')
    file_list = REPORT / 'files.f'
    sources = (SOC / 'files.f').read_text(encoding='utf-8')
    old = frozen.relative_to(ROOT).as_posix()
    assert sources.count(old) == 1
    file_list.write_text(sources.replace(old, bench.relative_to(ROOT).as_posix()), encoding='utf-8')
    upstream = 'build/server/official_2025/e203_hbirdv2-master/rtl/e203'
    includes = '+incdir+' + '+'.join((SOC.relative_to(ROOT).as_posix(), 'rtl/public_encoder',
                                     upstream + '/core', upstream + '/perips', upstream + '/perips/apb_i2c'))
    sim = REPORT / 'sim'
    job(['vcs', '-full64', '-sverilog', '+delay_mode_distributed', '+notimingcheck', '-timescale=1ns/1ps',
         '+define+ARM_UD_MODEL+DISABLE_SV_ASSERTION=1', includes, '-top', 'complete_soc_tb', '-f', file_list,
         '-Mdir=' + str(REPORT / 'csrc'), '-o', sim], REPORT / 'compile.log')
    job([sim, '+FIRST_TASK=1', '+TASKS=1', '+RESULT_DIR=' + REPORT.relative_to(ROOT).as_posix()], REPORT / 'run.log')
    log = (REPORT / 'run.log').read_text(encoding='utf-8')
    assert 'trace=25344 cycles=92317' in log and 'last_commit=92316 last_ack=92318' in log
    assert frozen.read_text(encoding='utf-8') == original
    print('SYSBUS32_BASELINE_OBSERVED', REPORT, flush=True)


if __name__ == '__main__':
    main()
