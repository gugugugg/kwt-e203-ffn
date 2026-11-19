"""Retire an old response before accepting a new final-write observation."""
import re

def reorder(text,gate=False,valid_expression=None,ready_expression=None):
    pattern=r'`ifndef KWT_UNIFIED_GATE\n(        if\(ld_final_pending&&dut\.shared_memory\.(joined_|cpu_)rsp_valid&&dut\.shared_memory\.\2rsp_ready\)begin\n            ld_result_complete=1;ld_final_pending=0;ld_last_ack=cycles;\n        end\n)`endif\n'
    matches=list(re.finditer(pattern,text))
    if len(matches)!=1:raise RuntimeError('Read the existing one-outstanding final-ACK observer')
    m=matches[0];body=m[1];prefix=m[2];text=text[:m.start()]+text[m.end():]
    if gate:
        body=body.replace('dut.shared_memory.'+prefix+'rsp_valid',valid_expression).replace('dut.shared_memory.'+prefix+'rsp_ready',ready_expression)
    else:body='`ifndef KWT_UNIFIED_GATE\n'+body+'`endif\n'
    marker='        if(activity_window&&ld_result_write)begin'
    if text.count(marker)!=1:raise RuntimeError('Read the actual physical shared-SRAM commit observer')
    return text.replace(marker,body+marker,1)

def mapped(text,valid_expression,ready_expression):
    text=reorder(text,True,valid_expression,ready_expression)
    marker='$display("UNIFIED_PUBLIC_TASK_PASS '
    at=text.index(marker)
    line='if(!ld_result_complete)$fatal(1,"CFE_MAPPED_FINAL_ACK_NOT_OBSERVED");\n$display("AR_AREA_MAPPED_ACK case=%0d last_commit=%0d last_ack=%0d",current_case,ld_last_commit-start_cycle,ld_last_ack-start_cycle);\n'
    return text[:at]+line+text[at:]
