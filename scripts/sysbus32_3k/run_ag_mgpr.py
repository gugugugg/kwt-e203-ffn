"""Build and accept the single AG private-memory clock-gating candidate."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import gzip
import os
import re
import shutil
import sys

from build_ch_efficiency import ROOT, RTL, SOC, replace
import run_ch_efficiency as ch

BASE = 'ffn_che_AG'
NAME = 'ffn_ag_mgpr'
PR = 'ffn_che_PR'
REPORT = ROOT/'reports/optimization'/NAME
ANCHOR = REPORT.parent/BASE
CORE_PATH = 'dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.core'
ROLES = (('weight_columns',16), ('input_banks',8), ('result_banks',16))


def gate_core(source):
    for bank, enable, reference in (
            ('weight', 'weight_read[col]||column_write', 'RAMSP128X16'),
            ('input', 'en', 'RAMSP1024X16'),
            ('result', 're||we', 'RAMSP128X16')):
        cen = '!en' if bank == 'input' else '!('+enable+')'
        old = '{} memory(.CLK(clk),.CEN({})'.format(reference, cen)
        gate = '''wire private_clk;
        kwt_ffn_clock_gate private_gate(.clk(clk),.enable(%s),.test_enable(1'b0),
            .gated_clk(private_clk));
        ''' % enable
        source = replace(source, old, gate+old.replace('.CLK(clk)', '.CLK(private_clk)'))
    return source


def build():
    enc = RTL/NAME/'encoder'
    enc.mkdir(parents=True, exist_ok=True)
    for source in (RTL/BASE/'encoder').glob('*.sv'):
        target = enc/source.name
        if source.name == 'kwt_threebank_core.sv':
            target.write_text(gate_core(source.read_text()))
        elif source.name == 'decode.sv':
            shutil.copyfile(RTL/PR/'encoder'/source.name,target)
        else:
            shutil.copyfile(source,target)
    parent, target = SOC/BASE, SOC/NAME
    for path in list(parent.iterdir())+list((parent/'eda').glob('*.tcl')):
        if path.is_file() and path.suffix in ('.v','.sv','.svh','.f','.json','.tcl','.rcf'):
            dest = target/path.relative_to(parent)
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(path.read_bytes().replace(BASE.encode(), NAME.encode()))
    fixtures = target/'packed_inputs'
    fixtures.mkdir(exist_ok=True)
    for path in (parent/'packed_inputs').glob('*.hex'):
        shutil.copyfile(path,fixtures/path.name)
    assert len(list(fixtures.glob('*.hex'))) == 36


def macro_paths(mapped=False):
    return [(CORE_PATH+'.'+(group+'_'+str(i)+'__memory' if mapped else group+'['+str(i)+'].memory'))
            for group,size in ROLES for i in range(size)]


def observer(bench, gate, mapped=False):
    before = '    initial begin'
    index = bench.index(before,bench.index('    string firmware_path='))
    source = ['    integer private_trace=0;',
              '    initial begin',
              '        string path;',
              '        if($value$plusargs("PRIVATE_TRACE=%s",path)) private_trace=$fopen(path,"w");',
              '    end']
    for i, mem in enumerate(macro_paths(mapped)):
        source.append('''
    if(1) begin: private_monitor_%d
        integer expected_edges=0, edges=0, reads=0, writes=0;
        bit sample, access, reading;
        reg [9:0] addr;
        reg [15:0] data, mask;
        always @(posedge clk) begin
            sample=activity_window;
            if(sample) begin
                if ($isunknown(%s.CEN)) $fatal(1,"Unknown CEN macro=%d");
                access=!%s.CEN;
                reading=%s.GWEN;
                if(access) begin
                    if ($isunknown(%s.GWEN)) $fatal(1,"Unknown GWEN macro=%d");
                    addr=10'(%s.A);
                    data=%s.D;
                    mask=%s.WEN;
                    if(reading) reads++;
                    else writes++;
                end
                if(%s) expected_edges++;
            end
        end
        always @(posedge %s.CLK) if(activity_window) edges++;
        always @(negedge clk) if(sample) begin
            if(edges!=expected_edges) $fatal(1,"MGPR clock mismatch macro=%d cycles=%%0d edges=%%0d expected=%%0d",cycles-start_cycle,edges,expected_edges);
            if(access&&private_trace)
                $fdisplay(private_trace,"%%0d %%0d %%0d %%03x %%04x %%04x",cycles-start_cycle,%d,reading,addr,
                    reading?16'b0:mask,reading?%s.Q:data);
        end
        final $display("MGPR_MACRO %d %%0d %%0d %%0d",reads,writes,edges);
    end''' % (i,mem,i,mem,mem,mem,i,mem,mem,mem,'access' if gate else "1'b1",mem,i,i,mem,i))
    source.append('    final if(private_trace) $fclose(private_trace);')
    return bench[:index]+'\n'.join(source)+'\n'+bench[index:]


def stats(path):
    data = re.findall(r'(?m)^MGPR_MACRO (\d+) (\d+) (\d+) (\d+)$', path.read_text())
    assert len(data)==40, path
    return {int(i):[int(rd),int(wr),int(clk)] for i,rd,wr,clk in data}


def compile_trace(variant, folder):
    folder.mkdir(parents=True,exist_ok=True)
    frozen = SOC/variant
    bench = folder/'complete_soc_tb.sv'
    bench.write_text(observer((frozen/'complete_soc_tb.sv').read_text(), variant==NAME))
    files = folder/'files.f'
    files.write_text(replace((frozen/'files.f').read_text(),
        (frozen/'complete_soc_tb.sv').relative_to(ROOT).as_posix(),bench.relative_to(ROOT).as_posix()))
    binary = folder/'sim'
    if not binary.is_file():
        upstream = 'build/server/official_2025/e203_hbirdv2-master/rtl/e203'
        includes = '+incdir+'+'+'.join((frozen.relative_to(ROOT).as_posix(),'rtl/public_encoder',
                                        upstream+'/core',upstream+'/perips',upstream+'/perips/apb_i2c'))
        ch.native.flow.job(['vcs','-full64','-sverilog','+delay_mode_distributed','+notimingcheck',
                            '-timescale=1ns/1ps','+define+ARM_UD_MODEL+DISABLE_SV_ASSERTION=1',
                            includes,'-top','complete_soc_tb','-f',files,'-Mdir='+str(folder/'csrc'),'-o',binary],
                           folder/'compile.log')
    return binary


def rtl_compare():
    work = REPORT/'bus-trace'
    parent, candidate = work/'ag-observation', work/'candidate'
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(compile_trace,BASE,parent)
        new = pool.submit(compile_trace,NAME,candidate)
        binaries = (old.result(),new.result())
    baseline = ch.native.flow.read(ANCHOR/'cpu-result.json')

    def one(row):
        ident = '%02d' % row['case']
        old_work, new_work = [folder/ident for folder in (parent,candidate)]
        for binary,folder in zip(binaries,(old_work,new_work)):
            folder.mkdir(exist_ok=True)
            log = folder/'run.log'
            private, bus = folder/'private.log', folder/'bus.log'
            archived = folder/'private.log.gz'
            if not log.is_file() or 'UNIFIED_PUBLIC_ALL_PASS tasks=1' not in log.read_text() or not bus.is_file() or not (private.is_file() or archived.is_file()):
                ch.native.flow.job([binary,'+FIRST_TASK='+str(row['case']),'+TASKS=1',
                                    '+RESULT_DIR='+str(folder),'+BUS_TRACE='+str(bus),
                                    '+PRIVATE_TRACE='+str(private)],log)
            text=log.read_text()
            assert 'UNIFIED_PUBLIC_ALL_PASS tasks=1' in text, log
            for marker in ('SYSBUS3K_COUNTS','UNIFIED_PUBLIC_TASK_PASS'):
                line, = re.findall(r'(?m)^'+marker+r' (.*)$',text)
                for name,value in re.findall(r'(\w+)=(\d+)',line):
                    assert int(value)==row[name], (ident,name,value,row[name])
        baseline_bus = ROOT/row['physical_trace']
        assert (new_work/'bus.log').read_bytes()==(old_work/'bus.log').read_bytes()==baseline_bus.read_bytes(), ident
        def trace(folder):
            plain = folder/'private.log'
            return plain.open('rt') if plain.is_file() else gzip.open(str(folder/'private.log.gz'),'rt')
        # Multiple ports can fire in the same cycle; compare identity independent of simulator process ordering.
        from itertools import groupby, zip_longest
        def ordered(stream):
            for _, lines in groupby(stream,lambda line:line.split(' ',1)[0]):
                yield sorted(lines)
        with trace(old_work) as ref,trace(new_work) as dut:
            for a,b in zip_longest(ordered(ref),ordered(dut)):
                assert a==b, (ident,a,b)
        old_counts,new_counts = [stats(folder/'run.log') for folder in (old_work,new_work)]
        for i,(rd,wr,edges) in new_counts.items():
            assert old_counts[i][:2]==[rd,wr] and edges==rd+wr, (ident,i)
        for folder in (old_work,new_work):
            plain = folder/'private.log'
            if plain.is_file():
                with plain.open('rb') as src, gzip.open(str(folder/'private.log.gz'),'wb',compresslevel=1) as out:
                    shutil.copyfileobj(src,out)
                plain.unlink()
        print('MGPR_RTL_PASS',row['case'],row['cycles'],sum(v[2] for v in new_counts.values()),flush=True)
        return dict(row,physical_trace=(new_work/'bus.log').relative_to(ROOT).as_posix(),
                    private_macros=new_counts)

    rows = [one(baseline['cases'][0])]
    with ThreadPoolExecutor(max_workers=ch.native.flow.settings()['cpu_case_workers']) as pool:
        rows.extend(pool.map(one,baseline['cases'][1:]))
    assert sum(row['cycles'] for row in rows)==545208
    ch.native.flow.write(work/'trace-result.json',dict(variant=NAME, baseline=BASE, cycles_total=545208,
        cases=rows, passed=True, baseline_edge_comparison=True, private_trace_comparison=True))
    ch.native.flow.write(REPORT/'cpu-result.json',dict(variant=NAME,cycles_total=545208,
        throughput=1800000000/545208,cases=rows))


def inspect(final):
    script = REPORT/'ag_mgpr_paths.tcl'
    log = REPORT/'ag_mgpr_paths.log'
    if not log.is_file() or 'MGPR_PATHS_DONE' not in log.read_text():
        prefix = (SOC/NAME/'eda/time.tcl').read_text().split('if {$assessment_setup < 0',1)[0]
        old = Path(__file__).with_name('ch_efficiency_paths.tcl').read_text()
        common = old.split('redirect $report/ch_efficiency_paths.rpt',1)[1]
        paths = old.split('redirect $report/ch_efficiency_paths.rpt',1)[0]
        paths = replace(paths,'if {[string match *ffn_che_AG* $tag]} {','if {1} {')
        paths = replace(paths,'} else {','}\nif {1} {')
        extra = Path(__file__).with_name('ag_mgpr_paths.tcl').read_text()
        script.write_text(prefix+paths+extra+'\nredirect $report/ag_mgpr_paths.rpt'+common.replace('CH_PATHS_DONE','MGPR_PATHS_DONE'))
        ch.native.flow.flow.run('pt_shell',script,log,dict(os.environ,XPIAN_TAG=final['tag'],XPIAN_CORNER='ss'))
    assert 'MGPR_PATHS_DONE' in log.read_text() and 'Error:' not in log.read_text(),log
    path_report = ROOT/'reports/server'/('complete_soc_sm40_'+final['tag'])/'pt/ag_mgpr_paths.rpt'
    assert path_report.is_file() and '(VIOLATED)' not in path_report.read_text(),path_report


def mapped_clock_wiring(netlist):
    design = netlist.read_text()
    core = re.search(r'(?ms)^module kwt_threebank_core\b.*?^endmodule',design)[0]
    gates = dict(re.findall(r'(?s)\bkwt_ffn_clock_gate\w*\s+(\w+)\s*\((.*?)\);',core))
    private = {name:pins for name,pins in gates.items() if 'private_gate' in name}
    assert len(private)==40
    assert len([g for g in gates if 'accum_clocks' in g])==64
    driven = {}
    for gate,pins in private.items():
        clock = re.search(r'\.gated_clk\(([^)]+)\)',pins)[1].strip()
        driven[clock] = gate
    buffers = {}
    for pins in re.findall(r'(?s)\bCLKBUF\w+\s+\w+\s*\((.*?)\);',core):
        port = dict((name,value.strip()) for name,value in re.findall(r'\.(\w+)\(([^)]+)\)',pins))
        if 'I' in port and 'Z' in port:
            buffers[port['Z']] = port['I']
    clock_names = {}
    for name in macro_paths(mapped=True):
        instance = name.rsplit('.',1)[1]
        macro = re.search(r'(?s)RAMSP\w+\s+'+instance+r'\s*\((.*?)\);',core)
        assert macro,instance
        clock = re.search(r'\.CLK\(([^)]+)\)',macro[1])[1].strip()
        source = clock
        while source in buffers:
            source = buffers[source]
        assert driven[source]==instance.replace('__memory','__private_gate'),instance
        clock_names[instance] = (clock,driven[source])
    predictor = re.search(r'(?s)RAMSP128X16\s+predictor_memory_+memory\s*\((.*?)\);',design)
    assert predictor and re.search(r'\.CLK\(([^)]+)\)',predictor[1])[1].strip()=='clk'
    return clock_names


def mapped_capture(final,cpu):
    netlist = ROOT/'build/server'/('complete_soc_sm40_'+final['tag'])/'netlist.v'
    clock_names = mapped_clock_wiring(netlist)
    orig = ch.verify.mapped_bench
    ch.verify.mapped_bench = lambda path: observer(orig(path),True,mapped=True)
    try:
        ch.verify.capture(final,cpu)
    finally:
        ch.verify.mapped_bench = orig
    rows=[]
    for row in cpu['cases']:
        log=REPORT/'gate-activity'/('run_%02d.log'%row['case'])
        rtl_counts={int(k):v for k,v in row['private_macros'].items()}
        saif=log.with_name('activity_%02d.saif'%row['case'])
        activity=saif.read_text()
        transitions={}
        for instance,(_,gate) in clock_names.items():
            gate_data=re.search(r'(?m)^ *\(INSTANCE '+re.escape(gate)+r'\s*$',activity)
            assert gate_data,(saif,gate)
            following=activity.find('(INSTANCE ',gate_data.end())
            gate_ports=activity[gate_data.end():following if following>=0 else len(activity)]
            entry=re.search(r'(?s)\(gated_clk\s+\(T0 .*?\(TC (\d+)\)',gate_ports)
            assert entry,(saif,gate)
            transitions[instance]=int(entry[1])
        for i,instance in enumerate(clock_names):
            assert abs(transitions[instance]-2*rtl_counts[i][2])<=1,(saif,instance,transitions[instance],rtl_counts[i])
        rows.append(dict(case=row['case'],rtl_macro_counts=rtl_counts,saif_clock_transitions=transitions))
    ch.native.flow.write(REPORT/'gate-activity/mgpr-private-result.json',
                         dict(tag=final['tag'],passed=True,cases=rows,
                              basis='RTL per-macro access and rising-edge observation checked against mapped SAIF TC'))


def power_check(final):
    power=ch.native.flow.read(REPORT/'gate-power/result.json')
    assert power['tag']==final['tag'] and len(power['measurements'])==12
    for row in power['measurements']:
        case=REPORT/'gate-power'/('case_%02d'%row['case'])
        log=(case/'pt.log').read_text()
        assert not re.search(r'(?m)^Error:',log),case
        nets=re.search(r'(?m)^\s*Nets\s+(\d+)\(100\.00%\)',(case/'annotation.rpt').read_text())
        assert nets and int(nets[1])>0,case


def main():
    ch.native.flow.preflight()
    REPORT.mkdir(parents=True,exist_ok=True)
    stage=sys.argv[1] if len(sys.argv)>1 else 'all'
    with ch.configured(NAME):
        if stage in ('all','rtl','screen'):
            build()
            if not (REPORT/'cpu-result.json').is_file():
                rtl_compare()
        if stage=='rtl':
            return
        if stage in ('all','screen'):
            if not (REPORT/'final-screen.json').is_file():
                ch.screen()
        if stage=='screen':
            return
        final=ch.native.flow.read(REPORT/'final-screen.json')
        assert final['timing_passed'], final
        inspect(final)
        if stage=='paths':
            return
        cpu=ch.native.flow.read(REPORT/'cpu-result.json')
        with ThreadPoolExecutor(max_workers=2) as pool:
            proof=pool.submit(ch.verify.prove,final)
            mapped_capture(final,cpu)
            proof.result()
        ch.verify.power(final)
        power_check(final)
        print('MGPR_MEASUREMENTS_COMPLETE',NAME,flush=True)


if __name__=='__main__':
    main()
