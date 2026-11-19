"""Capture pre-edge transactions from a frozen native three-bank case."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "trb_threebank"))
from native import ROOT, OUT, DEST, job, preflight, read, save
from native_delivery import ship
import native_delivery
from work_area import write_archive

REPORT = ROOT / "reports/optimization/ffn_trb_4x20_study"
NATIVE = REPORT / "native"
native_delivery.write_archive = write_archive

CORE = "dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.core"
ACC = CORE.rsplit(".", 1)[0]
FIELDS = [
    ("cycle", "cycles-start_cycle"), ("host_valid", "host_cmd_valid"), ("host_ready", "host_cmd_ready"),
    ("host_addr", "host_cmd_addr"), ("cpu_fire", "cpu_fire"), ("cpu_addr", "cpu_address"),
    ("cpu_read", "cpu_read"), ("cpu_rsp", "dut.shared_memory.cpu_rsp_valid&&dut.shared_memory.cpu_rsp_ready"),
    ("mmio_start", ACC+".start"), ("busy", CORE+".busy"),
    ("source_valid", "dut.ld_cmd_valid"), ("source_fire", "source_fire"), ("source_addr", "dut.ld_cmd_addr"),
    ("source_return", CORE+".src_response"), ("ingress", CORE+".ingress_count"), ("owner", CORE+".read_owner"),
    ("load", CORE+".load_fire"), ("load_param", CORE+".load_parameter"), ("pack", CORE+".pack_valid"),
    ("input_words", CORE+".input_words"), ("p0words", CORE+".page_words[0]"), ("p1words", CORE+".page_words[1]"),
    ("page_live", CORE+".page_live"), ("oldest", CORE+".oldest"), ("page_release", CORE+".page_release"),
    ("phase", CORE+".phase"), ("issue", CORE+".issue"), ("tile", CORE+".issue_tile"),
    ("pair", CORE+".issue_pair"), ("idx", CORE+".issue_index"),
    ("quant", CORE+".quant_valid"), ("qcol", CORE+".quant_col"), ("qside", CORE+".quant_side"),
    ("input_mask", CORE+".input_read_mask"), ("load_mask", CORE+".input_write_mask"),
    ("qmask", CORE+".quant_write_mask"), ("wread", CORE+".weight_read"), ("wwrite", CORE+".weight_write"),
    ("scratch", CORE+".scratch_read"), ("scratch_side", CORE+".scratch_side"),
    ("scratch_mask", CORE+".result_read_mask"), ("release", CORE+".release_mask"),
    ("s0", CORE+".slot_count[0]"), ("s1", CORE+".slot_count[1]"),
    ("write", "result_fire"), ("out_addr", "dut.wb_addr"), ("ack", "result_ack"),
    ("triple", "result_fire&&source_fire&&host_dual")
]


def capture():
    preflight()
    folder = NATIVE / "observation"
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "events.csv"
    source = OUT / "complete_soc_tb.sv"
    testbench = folder / source.name
    format_string = ",".join("%0d" for _ in FIELDS)
    fields = ",".join(expr for _,expr in FIELDS)
    header = ",".join(name for name,_ in FIELDS)
    observe = '''
    integer observe_events;
    initial begin
        observe_events=$fopen("%s","w");
        $fdisplay(observe_events,"%s");
    end
    always @(posedge clk) if(rst_n&&(activity_window||
        (ld_dma_writes==12672&&result_ack))) begin
        $fdisplay(observe_events,"%s",%s);
    end
''' % (output.relative_to(ROOT).as_posix(),header,format_string,fields)
    content = source.read_text()
    head, end = content.rsplit("endmodule",1)
    testbench.write_text(head+observe+"endmodule"+end)
    files = (OUT / "files.f").read_text().replace(source.relative_to(ROOT).as_posix(),
                                                testbench.relative_to(ROOT).as_posix())
    filelist = folder / "files.f"
    filelist.write_text(files)
    upstream = "build/server/official_2025/e203_hbirdv2-master/rtl/e203"
    include = "+incdir+" + "+".join((OUT.relative_to(ROOT).as_posix(), "rtl/public_encoder",
        upstream+"/core",upstream+"/perips",upstream+"/perips/apb_i2c"))
    sim=folder/"sim"
    job(["vcs","-full64","-sverilog","+delay_mode_distributed","+notimingcheck",
         "-timescale=1ns/1ps","+define+ARM_UD_MODEL+DISABLE_SV_ASSERTION=1",
         include,"-top","complete_soc_tb","-f",filelist,"-Mdir="+str(folder/"csrc"),"-o",sim],
        folder/"compile.log")
    run=folder/"run_01.log"
    job([sim,"+FIRST_TASK=1","+TASKS=1","+RESULT_DIR="+folder.relative_to(ROOT).as_posix()],run)
    for marker in ("THREEBANK_COUNTS","UNIFIED_PUBLIC_TASK_PASS"):
        def entry(path):
            return next(line for line in path.read_text().splitlines() if line.startswith(marker))
        assert entry(run)==entry(DEST/"run_01.log")
    ship(REPORT,"observation",[output,run,folder/"compile.log",testbench,filelist])


if __name__=="__main__":
    capture()
