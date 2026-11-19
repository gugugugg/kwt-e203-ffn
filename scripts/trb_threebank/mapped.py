"""Observe physical output writes from the final mapped SRAM input pins."""
from pathlib import Path
import re

from native import ROOT, NAME, REPORT, OUT, DEST, read, save, job


def paths(netlist):
    modules={m[1]:m[2] for m in re.finditer(r"(?ms)^module\s+(\w+)\b(.*?)^endmodule",netlist)}
    tcm={}
    shared={}

    def walk(name, prefix):
        for reference, instance in re.findall(r"(?m)^\s*(\w+)\s+(\\\S+|[\w$]+)\s*\(",modules[name]):
            path=prefix+"."+instance+(" " if instance.startswith("\\") else "")
            if reference=="RAMSP4KX64" and "u_e203_itcm_ram" in path:
                tcm[int(re.search(r"banks[^0-9]*(\d+)",instance)[1])]=path
            elif reference=="RAMSP4096X16" and ".shared_memory." in path:
                bank=int(re.search(r"banks[^0-9]*(\d+)",instance)[1])
                half=int(re.search(r"halves[^0-9]*(\d+)",instance)[1])
                shared.setdefault(bank,{})[half]=path
            elif reference in modules:
                walk(reference,path)

    walk("kwt_complete_soc","dut")
    assert set(tcm)==set(range(8)) and all(set(shared[b])=={0,1} for b in (4,5,6,7,31))
    return tcm,shared


def preload(tcm, mailbox):
    lines=["        @(negedge reference_clk);",
           "        for(integer b=0;b<boot_count;b=b+1) begin",
           "            case(b>>12)"]
    for bank,path in sorted(tcm.items()):
        lines.append("                %d: for(integer k=0;k<64;k=k+1) "
                     "%s.mem[(b&4095)>>3][k*8+(b&7)]=boot_words[b][k];"%(bank,path))
    lines+=["            endcase","        end","        for(integer b=0;b<64;b=b+1) begin"]
    for half,path in sorted(mailbox.items()):
        lines.append("            for(integer k=0;k<16;k=k+1) %s.mem[(4032+b)>>3][k*8+(b&7)]="
                     "b==3 ? ((requested_tasks >> (k+%d)) & 1) : 1'b0;"%(path,half*16))
    lines+=["        end","        host_idle();","        boot_phase=0;",
            "        @(negedge reference_clk);rst_n=1;","        wait(system_reset_n===1'b1);"]
    return "\n".join(lines)


def physical_probe(shared):
    lines=["    reg [3:0] result_bank_write;", "    reg [16:0] physical_result_addr;",
           "    reg [31:0] physical_result_data;", "    always @* begin",
           "        result_bank_write=0;physical_result_addr=0;physical_result_data=0;"]
    for bank in range(4,8):
        lo,hi=shared[bank][0],shared[bank][1]
        lines.append("        if(!%s.CEN&&!%s.GWEN&&!%s.CEN&&!%s.GWEN&&"
                     "%s.WEN==0&&%s.WEN==0%s) begin"%(lo,lo,hi,hi,lo,hi,
                         "&&"+lo+".A<12'h180" if bank==7 else ""))
        lines.append("            result_bank_write[%d]=1;physical_result_addr={5'd%d,%s.A};"
                     "physical_result_data={%s.D,%s.D};"%(bank-4,bank,lo,hi,lo))
        lines.append("        end")
    lines+=["    end", "    wire result_fire=|result_bank_write;",
            "    always @(posedge clk) if(activity_window&&$countones(result_bank_write)>1) "
            '$fatal(1,"MULTIPLE_RESULT_MACRO_WRITES");']
    return "\n".join(lines)


def run(screen, cpu, review):
    assert review["tag"]==screen["tag"] and review["reviewed"]
    netlist=ROOT/"build/server"/("complete_soc_sm40_"+screen["tag"])/"netlist.v"
    tcm,shared=paths(netlist.read_text())
    bench=(OUT/"complete_soc_tb.sv").read_text()
    bench=re.sub(r"(?m)^\s*wire \[31:0\] inspect_pc=.*;\n","\n",bench)
    bench=bench.replace(" pc=%h","").replace(",inspect_pc","")
    for field in ("cpu_fire","cpu_address","cpu_data","cpu_read","source_fire","result_ack"):
        bench,n=re.subn(r"(?m)(^\s*wire (?:\[31:0\] )?"+field+r"=)[^;]*;",lambda m:
                         m[1]+review["expressions"][field]+";",bench)
        assert n==1,field
    bench=re.sub(r"(?m)^    wire \[3:0\] cpu_mask=.*;\n","",bench)
    bench=bench.replace("    wire result_fire=dut.wb_valid&&dut.wb_ready;",physical_probe(shared))
    bench=bench.replace("int'(dut.wb_addr)","int'(physical_result_addr)").replace(
                         "dut.wb_addr,", "physical_result_addr,").replace("dut.wb_data","physical_result_data")
    begin=bench.index("        force dut.shared_memory.clk=reference_clk;")
    end=bench.index("        wait(system_reset_n===1'b1);",begin)+len("        wait(system_reset_n===1'b1);")
    bench=bench[:begin]+preload(tcm,shared[31])+bench[end:]
    bench=re.sub(r'(?ms)`ifdef KWT_UNIFIED_GATE\n    string sdf_path;.*?`endif\n','',bench)
    target=OUT/"gate_tb.sv"
    target.write_text(bench)
    models=[line for line in (OUT/"files.f").read_text().splitlines() if
            ("/mem_gen/" in line or line.startswith("/storage1/") or
             line.endswith("/ROM1KX32.v") or "scc40nll_vhsc40_rvt.v" in line)]
    files=OUT/"gate_files.f"
    files.write_text("\n".join(models+[netlist.relative_to(ROOT).as_posix(),
                                      target.relative_to(ROOT).as_posix()])+"\n")
    binary=OUT/"mapped_functional_sim"
    job(["vcs","-full64","-sverilog","+delay_mode_distributed","+notimingcheck",
         "-timescale=1ns/1ps","+define+ARM_UD_MODEL+KWT_UNIFIED_GATE+DISABLE_SV_ASSERTION=1",
         "+incdir+"+OUT.relative_to(ROOT).as_posix(),"-top","complete_soc_tb",
         "-f",files,"-Mdir="+str(OUT/"gate_csrc"),"-o",binary],DEST/"mapped_compile.log")
    results=OUT/"mapped_results"
    results.mkdir(exist_ok=True)
    log=DEST/"mapped_01.log"
    job([binary,"+FIRST_TASK=1","+TASKS=1","+RESULT_DIR="+results.relative_to(ROOT).as_posix()],log)
    data=log.read_text()
    task=re.search(r"(?m)^UNIFIED_PUBLIC_TASK_PASS (.*)$",data)
    counts=re.search(r"(?m)^THREEBANK_COUNTS (.*)$",data)
    assert task and counts and "UNIFIED_PUBLIC_ALL_PASS" in data
    parsed={k:int(v) for k,v in re.findall(r"(\w+)=(\d+)",task[1]+" "+counts[1])}
    assert parsed["checked_physical_addresses"]==12672 and parsed["outputs"]==25344
    assert parsed["cycles"]==cpu["cases"][0]["cycles"]
    for key in ("reads","writes","acks","last_commit","last_ack"):
        assert parsed[key]==cpu["cases"][0]["counts"][key],(key,parsed[key])
    save(DEST/"mapped_evaluation.json",dict(variant=NAME,tag=screen["tag"],passed=True,
         case=1,physical_macro_pin_observation=True,functional=True,counts=parsed))

