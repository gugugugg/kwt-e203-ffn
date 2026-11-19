"""Instrument complete-SoC cold windows at the physical result write edge."""
from pathlib import Path


def make_bench(parent):
    prefix = parent[:parent.index('    string filename,mode_name')]
    prefix += parent[parent.index('    realtime activity_begin'):parent.index('    bit firmware_done=0;')]
    prefix += '    bit firmware_done=0;\n'
    prefix += parent[parent.index('    task command_phase;'):parent.index('    task put_word')].split('endtask')[0]+'endtask\n'
    prefix += parent[parent.index('    task put_word'):parent.index('    always @(posedge clk) if(rst_n) begin')]
    boot = parent[parent.index('        force dut.shared_memory.clk=reference_clk;'):
                  parent.index('        for(task_number=0;task_number<requested_tasks;')]
    return prefix + (Path(__file__).parent / "bench_body.svh").read_text().replace("/* BOOT */", boot)

