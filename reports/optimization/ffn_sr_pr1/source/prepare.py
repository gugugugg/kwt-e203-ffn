"""Derive the one PR1 endpoint after the calibrated cold-task screen."""
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
NAME = 'ffn_sr_pr1'
PARENT = 'ffn_ara_SR'
REPORT = ROOT / 'reports/optimization' / NAME
OLD = ROOT / 'build/optimization/complete_soc' / PARENT
ENDPOINT = 'kwt_shared_dma_icb_sm40.sv'


def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Expected a single frozen SR match: ' + before)
    return text.replace(before, after, 1)


def transform(text):
    text = replace(text, 'reg joined_rsp_valid;', 'wire joined_rsp_valid;\nreg stored_rsp_valid;')
    text = replace(text, 'reg [31:0] joined_rsp_rdata;', 'wire [31:0] joined_rsp_rdata;\nreg [31:0] stored_rsp_rdata;')
    text = replace(text, 'reg joined_rsp_err;', 'wire joined_rsp_err;\nreg stored_rsp_err;\nwire joined_cmd_dma;')
    text = replace(text, '        .s_cmd_read(joined_cmd_read),',
                   '        .s_cmd_read(joined_cmd_read),\n        .s_cmd_dma(joined_cmd_dma),')
    text = replace(text, """    reg pending,read_pending,error_pending,to_host;
    wire idle=!pending&&!joined_rsp_valid&&!host_rsp_valid;
    assign host_cmd_ready=idle;
    assign read_handoff_allowed=!pending&&!host_cmd_valid&&!host_rsp_valid;""", """    reg pending,read_pending,error_pending,to_host,pending_fast_read;
    wire [31:0] memory_rdata;
    wire next_fast_read=joined_cmd_dma&&joined_cmd_read&&(joined_cmd_addr[1:0]==2'b00)&&
                        (joined_cmd_addr>=32'ha0020000)&&(joined_cmd_addr<32'ha0028800);
    wire early_response=pending&&pending_fast_read;
    assign joined_rsp_valid=early_response||stored_rsp_valid;
    assign joined_rsp_rdata=early_response?memory_rdata:stored_rsp_rdata;
    assign joined_rsp_err=!early_response&&stored_rsp_err;
    wire idle=!pending&&!stored_rsp_valid&&!host_rsp_valid;
    assign host_cmd_ready=idle;
    assign read_handoff_allowed=(!pending||(early_response&&next_fast_read))&&
                               !host_cmd_valid&&!host_rsp_valid;""")
    text = replace(text, '    wire [31:0] memory_rdata;\n    wire physical_accept=', '    wire physical_accept=')
    begin = text.index('            pending<=0;read_pending<=0;error_pending<=0;')
    end = text.index('        end\n    end\nendmodule', begin)
    text = text[:begin] + """            pending<=0;read_pending<=0;error_pending<=0;pending_fast_read<=0;
            stored_rsp_valid<=0;stored_rsp_rdata<=0;stored_rsp_err<=0;
            host_rsp_valid<=0;host_rsp_rdata<=0;to_host<=0;
        end else begin
            if(stored_rsp_valid&&joined_rsp_ready) stored_rsp_valid<=0;
            if(host_rsp_valid&&host_rsp_ready) host_rsp_valid<=0;
            if(pending) begin
                pending<=0;
                if(to_host) begin
                    host_rsp_valid<=1;host_rsp_rdata<=memory_rdata;
                end else if(!early_response||!joined_rsp_ready) begin
                    stored_rsp_valid<=1;stored_rsp_err<=error_pending;
                    stored_rsp_rdata<=(read_pending&&!error_pending)?memory_rdata:32'b0;
                end
            end
            // A new accept may share the edge with retirement of the old SRAM Q.
            if(joined_fire) begin
                pending<=1;read_pending<=joined_cmd_read;
                error_pending<=!joined_address_valid;to_host<=0;
                pending_fast_read<=next_fast_read;
            end
            if(host_fire&&host_cmd_read) begin
                pending<=1;read_pending<=1;error_pending<=0;to_host<=1;
                pending_fast_read<=0;
            end
""" + text[end:]
    text = replace(text, '    output wire s_cmd_read,output wire [31:0] s_cmd_wdata',
                   '    output wire s_cmd_read,output wire s_cmd_dma,output wire [31:0] s_cmd_wdata')
    return replace(text, '    assign s_cmd_read=grant?b_cmd_read:a_cmd_read;',
                   '    assign s_cmd_read=grant?b_cmd_read:a_cmd_read;\n    assign s_cmd_dma=grant;')


def main():
    model = json.loads((REPORT / 'model-results.json').read_text())
    if not (model['calibrated'] and model['functional_passed'] and model['timing_eligible']):
        raise RuntimeError('PR1 cold model did not pass')
    selected = ROOT / 'constraints/ffn_selected.json'
    receipt = ROOT / 'reports/submission/ara-SR-release-20261105/completion.json'
    baseline = json.loads(receipt.read_text())
    if json.loads(selected.read_text())['variant'] != PARENT or not baseline['complete']:
        raise RuntimeError('Expected frozen SR release')
    shutil.copyfile(selected, REPORT / 'baseline-selected.json')
    shutil.copyfile(receipt, REPORT / 'baseline-release.json')
    (REPORT / ENDPOINT).write_text(transform((OLD / ENDPOINT).read_text()), encoding='ascii', newline='\n')
    target = dict(variant=NAME, reference=PARENT, maximum_cycles_exclusive=sum(baseline['cycles']),
                  maximum_area_exclusive_mm2=0.300, maximum_mean_energy_j=baseline['mean_energy_j'])
    (REPORT / 'objective.json').write_text(json.dumps(target, indent=2) + '\n')


if __name__ == '__main__':
    main()
