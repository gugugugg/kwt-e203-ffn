"""Read the selected K8-3 netlist and native segment evidence."""
import itertools
import json
import re
import shutil
import sys

from native import NAME, ROOT, phases
from sr_area_phase_review import native_index


class Evidence:
    def __init__(self):
        _, self.report, self.archive, self.review = phases.bind('P2', variant=NAME)
        extra = self.review/'phase-extra-segments'
        returned = self.report/'received/segments/native-evidence'/extra.relative_to(self.archive)
        for file in returned.iterdir():
            if file.name == 'targets.json':
                assert file.read_bytes() == (extra/file.name).read_bytes()
            else:
                shutil.copyfile(file, extra/file.name)
        self.inventory = self.read('inventory')
        self.conn = self.read('connectivity')
        self.cells = self.inventory['cells']
        self.tag = self.inventory['tag']
        report = json.loads((extra/'result.json').read_text())
        assert report['passed'] and report['tag'] == self.tag
        self.models = {name: body.split('specify')[0] for name, body in re.findall(
            r'\bmodule\s+(\w+)\s*\(([\s\S]*?)endmodule', (self.review/'vendor-functions.v').read_text())}
        self.segments = {}
        for folder in (self.review, self.review/'additional-segments', extra):
            self.segments.update(native_index(folder/'segments.rpt'))
        self.rtl = ROOT/'build/optimization/rtl_sources'/NAME/'encoder'
        self.core, = [path for path in self.cells if path.endswith('/accelerator/controller/core')]

    def read(self, name):
        return json.loads((self.review/(name+'.json')).read_text())

    def write(self, name, value):
        (self.review/(name+'.json')).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')

    def rep(self, net):
        return self.conn['representatives'].get(net, net)

    def port(self, cell, pin):
        return self.rep(self.conn['pins'][cell+'/'+pin])

    def driver(self, net):
        row, = self.conn['drivers'][self.rep(net)]
        return dict(row, pins={key: value.strip() for key,value in self.cells[row['cell']]['pins'].items()})

    def literal(self, ref, primitive, pins):
        assert re.search(r'\b'+primitive+r'\s+(?:\w+\s*)?\(\s*'+
                         r'\s*,\s*'.join(map(re.escape,pins.split(',')))+r'\s*\)', self.models[ref]), (ref,pins)

    def prove(self, net, leaves, expected):
        logic = re.compile(r'\b(buf|not|and|nand|or|nor|xor|xnor|udp_mux2)\s+(?:\w+\s*)?\(([^;()]+)\)')
        ops = {
            'buf': lambda x: x, 'not': lambda x: not x,
            'and': lambda *x: all(x), 'nand': lambda *x: not all(x),
            'or': lambda *x: any(x), 'nor': lambda *x: not any(x),
            'xor': lambda *x: sum(x)%2, 'xnor': lambda *x: not sum(x)%2,
            'udp_mux2': lambda a,b,s: b if s else a,
        }
        keys = {self.rep(n): i for i,n in enumerate(leaves)}
        assert len(keys)==len(leaves)
        cone, cache = {}, {}

        def expr(name):
            name = self.rep(name)
            if name in keys:
                return lambda row: row[keys[name]]
            if name in cache:
                return cache[name]
            cell = self.driver(name)
            cone[cell['cell']] = cell
            equations = {}
            for gate,pins in logic.findall(self.models[cell['ref']].split('`ifdef')[0]):
                output,*terms = [pin.strip() for pin in pins.split(',')]
                equations[output] = gate,terms

            def node(pin):
                if pin not in equations:
                    value = cell['pins'][pin]
                    if value in ("1'b0","1'b1"):
                        return lambda _: value[-1]=='1'
                    return expr(self.port(cell['cell'],pin))
                gate,terms = equations[pin]
                subs = [node(term) for term in terms]
                return lambda row: ops[gate](*(sub(row) for sub in subs))

            value = cache[name] = node(cell['pin'])
            return value

        actual = expr(net)
        for values in itertools.product((False,True),repeat=len(leaves)):
            assert actual(values)==bool(expected(*values)), (net,leaves,values)
        return dict(leaves=leaves,truth_rows=2**len(leaves),cone=list(cone.values()))

    def mapped_ack(self):
        engine, = [name for name in self.cells if name.endswith('/dma_frontend/loading_dma')]
        arbiter = 'shared_memory/memory_arbiter'
        for module,prefix in [('shared_memory','ld_'),('soc','ld_'),(arbiter,'b_'),(engine,'mem_')]:
            parent = module.rpartition('/')[0]
            for signal in ('valid','ready'):
                terminal = prefix+'rsp_'+signal+('_BAR' if signal=='ready' else '')
                pin = self.cells[module]['pins'][terminal].strip()
                assert self.rep('/'.join(part for part in (parent,pin) if part))==self.rep('ld_rsp_'+signal)
        ready,valid = self.driver('ld_rsp_ready'),self.driver('ld_rsp_valid')
        active=engine+'/busy'
        active_driver=self.driver(active)
        assert active_driver['cell']==engine+'/pd_active_reg' and active_driver['pin']=='Q'
        ready_cone=self.prove('ld_rsp_ready',[active],lambda q:not q)
        assert 'assign mem_rsp_ready=pd_active;' in (self.rtl/'kwt_ld_engine.sv').read_text()
        self.literal(active_driver['ref'],'buf','Q,n0')
        self.literal(valid['ref'],'and','Z,A1,A2')
        assert valid['cell'].startswith(arbiter+'/') and 's_rsp_valid' in valid['pins'].values()
        self.write('mapped-ack-interface',dict(passed=True,tag=self.tag,variant=NAME,
            valid_expression='dut.ld_rsp_valid',ready_expression='(!dut.ld_rsp_ready)',
            connections=dict(valid=valid,ready=ready,positive_state=active_driver,ready_cone=ready_cone)))


    def resolve(self):
        draft = self.read('corrections-draft')
        records = self.read('physical-cell-phase-review')
        pending = self.read('phase-review-pending')
        cell_inputs = {row['rtl']:row for row in self.read('cell-inverted-review-inputs')}
        reset_cases = {'address','words','csr_rsp_data','csr_rsp_valid','csr_rsp_err',
                       'chain','chain_error','chain_address','chain_words','chain_pending'}
        frontend = (self.rtl/'kwt_ld_frontend.sv').read_text()
        core_rtl = (self.rtl/'kwt_encoder.sv').read_text()
        assert 'if(!rst_n)begin address<=0;words<=0;csr_rsp_valid<=0;csr_rsp_err<=0;csr_rsp_data<=0;' in frontend
        assert 'chain<=CH_IDLE;chain_address<=0;chain_words<=0;chain_pending<=0;chain_error<=0;' in frontend
        assert 'wp_execute_token<=wp_capture_token;' in core_rtl and 'wp_execute_token<=0;' in core_rtl
        core = self.core
        def names(scope,*signals):
            return [scope+'/'+n for n in signals]

        for row in pending:
            if row['kind']=='net_semantics':
                net=row['segment']
                if net=='shared_memory/memory/en_BAR':
                    shared='shared_memory'
                    address=names(shared,*('joined_cmd_addr[%d]'%i for i in range(19,32)))
                    qualified=self.prove(shared+'/n307',address,
                        lambda *a:sum(int(b)<<i for i,b in enumerate(a))!=0x1400)
                    proof=self.prove(net,names(shared,'host_cmd_ready','host_cmd_valid',
                        'joined_cmd_ready','joined_cmd_valid','n307'),
                        lambda hr,hv,jr,jv,no_address:not (hr and hv or jr and jv and not no_address))
                    proof['address_valid']=qualified
                    reason='Actual gate is the complement of physical_accept. A dual host write requires a valid joined read.'
                else:
                    assert net==core+'/wave_weight_stage_3__weight_stage_gate/enable_BAR'
                    leaves=names(core,*('state[%d]'%i for i in range(5)),
                                 'wp_capture_token[13]','wp_capture_token[8]','wp_capture_token[7]',
                                 'wave_schedule_2__execute[11]')
                    proof=self.prove(net,leaves,lambda a,b,c,d,e,v,q1,q0,w:
                        not (v and q1 and q0) if e and not (a or b or c or d) else not w)
                    reason='Actual weight-return clock enable segment is the complement of quartet 3 capture.'
                for a in row['aliases']:
                    draft['aliases'].append(dict(rtl=a['rtl'],gate=a['gate'],inverted=True,
                        reason=reason,evidence=dict(proof=proof,native=self.segments['net',a['gate']])))
                draft['reviewed_bar_segments'].append(dict(segment=net,reason=reason,aliases=len(row['aliases'])))
                continue

            assert row['kind']=='cell_encoding',row
            rtl,cell,ref=row['rtl'],row['cell'],row['ref']
            scope=cell.rsplit('/',1)[0]
            bits=rtl.rsplit('/',1)[-1]
            signal=bits.split('[')[0]
            pins={key:value.strip() for key,value in self.cells[cell]['pins'].items()}
            output='QN' if 'QN' in pins else 'Q'
            self.literal(ref,'not' if output=='QN' else 'buf',output+',n0')
            evidence=dict(cell=cell,pins=pins,
                native={pin:self.segments.get(('pin',cell+'/'+pin)) for pin in pins})
            assert evidence['native'][output] is not None
            if signal in reset_cases and scope.endswith('/dma_frontend'):
                assert ref=='DRNQNV4_12TR40'
                self.literal(ref,'buf','xRN,RDN')
                self.literal(ref,'udp_dff','n0,D,clk,xRN,xSN,NOTIFIER')
                evidence['reset']=self.prove(self.port(cell,'RDN'),names(scope,'rst_n'),lambda rst:rst)
                negative=True
                reason='Original reset-zero frontend state. The actual active-low reset clears internal state and literal QN inverts it.'
            elif signal=='wp_execute_token':
                assert ref=='DSNQNV6_12TR40'
                self.literal(ref,'buf','xSN,SDN')
                self.literal(ref,'udp_dff','n0,D,clk,xRN,xSN,NOTIFIER')
                evidence['reset']=self.prove(self.port(cell,'SDN'),names(core,'rst_n'),lambda rst:rst)
                boot=core+'/output_queue/write_transposed'
                start=core+'/n_89_net_'
                evidence['boot']=self.prove(boot,names(core,*('state[%d]'%i for i in range(5))),
                    lambda *a:sum(int(v)<<i for i,v in enumerate(a))==16)
                evidence['start']=self.prove(start,names(core,'layer_start_valid','layer_start_ready'),
                    lambda valid,ready:valid and ready)
                captured='wp_capture_token'+bits[len(signal):]
                evidence['D']=self.prove(self.port(cell,'D'),names(core,captured,bits)+[boot,start],
                    lambda data,old,wp,init:not (data if wp else False if init else old))
                negative=False
                reason='Actual set-one internal reset and complementary D encoding yield the original positive execute token on QN.'
            else:
                assert signal=='qout_r',row
                din=scope+'/dnxt'+bits[len(signal):]
                if ref=='EDQNV6_12TR40':
                    self.literal(ref,'udp_edff','n0,D,CK,xRN,xSN,E,NOTIFIER')
                    evidence['enable']=self.prove(self.port(cell,'E'),names(scope,'lden'),lambda e:e)
                    evidence['D']=self.prove(self.port(cell,'D'),[din],lambda data:not data)
                    negative=False
                else:
                    assert ref in ('DQV0_12TR40','DRSNQNV2_12TR40')
                    self.literal(ref,'udp_dff','n0,D,clk,xRN,xSN,NOTIFIER')
                    evidence['D']=self.prove(self.port(cell,'D'),names(scope,'lden',pins[output])+[din],
                        (lambda enable,old,data:not (data if enable else old)) if output=='QN'
                        else (lambda enable,old,data:not data if enable else old))
                    negative=output=='Q'
                    if not negative:
                        assert pins['RDN']=="1'b1"
                        self.literal(ref,'buf','xSN,SDN')
                        evidence['reset']=self.prove(self.port(cell,'SDN'),names(scope,'rst_n'),lambda rst:rst)
                reason='Physical FIFO state encoding follows the recorded input and feedback cone and the literal vendor output function.'
            target=cell_inputs[rtl][output+'_net']
            records.append(dict(rtl=rtl,physical_inverted=negative,output=output,net=target,
                                reason=reason,evidence=evidence))
            if negative:
                draft['replace_native_cell_aliases'].append(rtl)
                draft['aliases'].append(dict(rtl=rtl,gate=target,inverted=True,reason=reason,evidence=evidence))
        draft['pending']=0
        self.write('physical-cell-phase-review',records)
        self.write('corrections-draft',draft)
        self.write('k8-physical-review',dict(tag=self.tag,resolved=len(pending),
                                           aliases=len(draft['aliases']),replaced=len(draft['replace_native_cell_aliases'])))
        phases.phase.local_review('assemble')

    def resolve_duplicate_aliases(self):
        expected=self.read('phase-expectations')['nets']
        verdict=json.loads((self.report/'phase-verdict.json').read_text())
        assert not verdict['passed'] and verdict['attempt']=='probe-attempt-01'
        corrections=self.read('corrections-draft')
        primary={
            'cmt_dpc_ena_BAR': '/step_req_dfflr/dnxt[0]',
            'rst_n_BAR': '/u_jtag_ResetCatchAndSync_3_1/io_sync_reset',
            'io_sync_reset': '/aonrst_catch/io_sync_reset',
            'we_BAR': '/u_sirv_1cyc_sram_ctrl/uop_cmd_read',
        }
        reviewed={}
        for row in verdict['mismatches']:
            net=row['net']
            segment=self.rep(net)
            if segment in reviewed:
                continue
            sources=expected[net]['sources']
            suffix=primary[segment.rsplit('/',1)[-1]]
            canonical, = [s for s in sources if s['rtl'].endswith(suffix) and not s['inverted']]
            reason='Retain the original positive signal on this verified physical segment and exclude competing aliases.'
            corrections['aliases'].append(dict(rtl=canonical['rtl'],gate=net,inverted=False,
                reason=reason,evidence=dict(driver=self.driver(net),native=self.segments.get(('net',net)))))
            suppress=sorted({s['rtl'] for s in sources if s['rtl']!=canonical['rtl']})
            corrections['deduplicated_positive_aliases']=sorted(set(
                corrections.get('deduplicated_positive_aliases',[]))|set(suppress))
            reviewed[segment]=dict(positive_source=canonical,excluded=suppress,driver=self.driver(net))
        assert len(reviewed)==4
        self.write('k8-duplicate-segment-review',reviewed)
        self.write('corrections-draft',corrections)
        phases.phase.local_review('assemble')

if __name__ == '__main__':
    evidence = Evidence()
    if sys.argv[1:] == ['ack']:
        evidence.mapped_ack()
    elif sys.argv[1:] == ['resolve']:
        evidence.resolve()
    elif sys.argv[1:] == ['aliases']:
        evidence.resolve_duplicate_aliases()
    else:
        for row in evidence.read('phase-review-pending'):
            print(row.get('rtl',row.get('segment')),row.get('cell'),row.get('ref'))



