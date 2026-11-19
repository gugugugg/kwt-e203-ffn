"""Causal 16/20-column comparison with pre-edge transport and private SRAM state."""
from concurrent.futures import ProcessPoolExecutor
import csv
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("threebank_reference",HERE.parent/"trb_threebank/screen.py")
reference=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
ThreeBankTask, base=reference.ThreeBankTask,reference.base

ROOT = HERE.parents[1]
REPORT = ROOT / "reports/optimization/ffn_trb_4x20_study"
OBSERVATION = REPORT/"received/observation/native-evidence"/REPORT.relative_to(ROOT)/"native/observation/events.csv"
EVENTS = ("host", "source_fire", "source_return", "load", "issue", "quant", "scratch",
          "write", "ack", "page_release", "triple")
IDENTITY_FIELDS = {"host": ("host_addr",), "source_fire": ("source_addr",),
                   "issue": ("tile", "pair", "idx"), "quant": ("qcol", "qside"),
                   "scratch": ("scratch_side",), "write": ("out_addr",),
                   "page_release": ("oldest",)}


class Layout:
    def __init__(self, stride):
        self.stride = stride
        self.widths = [min(stride, 256-c) for c in range(0,256,stride)]
        self.sizes = [33*w+w//4 for w in self.widths]
        self.positions = [(tile, offset) for tile,n in enumerate(self.sizes) for offset in range(n)]
        assert len(self.positions) == 8512
        self.limits = ((1024-832)//stride,(1024-768)//stride)

    def param(self, addr):
        return self.positions[addr-base.PARAMETER_BASE]

    def pack(self, case):
        source, _, identities = base.payload(case)
        source = {k:v for k,v in source.items() if k<base.INPUT_WORDS}
        _, weights, bias, shift = base.baseline.q16.q8.m3.r3o.vectors(case)
        packets = []
        start = base.PARAMETER_BASE
        for tile,width in enumerate(self.widths):
            col = tile*self.stride
            words = [value & 0xffffffff for value in bias[col:col+width]]
            words.extend(sum((shift[i+j]&255)<<(8*j) for j in range(4))
                         for i in range(col,col+width,4))
            for k in range(64):
                off = 256*k+col
                words.extend(base.packed(weights[off+i],weights[off+i+1]) for i in range(0,width,2))
            packet = list(range(start,start+self.sizes[tile]))
            assert len(words)==len(packet)
            source.update(zip(packet,words))
            packets.append(packet)
            start += len(packet)
        order = packets[0]+list(range(1024))+packets[1]+list(range(1024,3168))
        order.extend(word for packet in packets[2:] for word in packet)
        return source, order, identities


class Slot(base.Slot):
    def __init__(self, side, index, tile, group, sequence, layout):
        super().__init__(side,index,tile,group,sequence)
        self.width = layout.widths[tile]
        self.stride = layout.stride
        self.completed_edge = None

    @property
    def words(self):
        return (3 if self.group==24 else 4)*self.width//2

    def cell(self, row, col):
        return 4*self.side+(row^(col&1)), (832,768)[self.side]+self.stride*self.index+col


class Task(ThreeBankTask):
    def __init__(self, case, stride, startup):
        super().__init__(case,startup["controls"],startup["start"],startup["host_start"],startup["cpu_setup"])
        self.layout=Layout(stride)
        self.source,self.order,self.identities=self.layout.pack(case)
        self.host_order=[(0,self.source[0])]+startup["controls"]
        self.host_order.extend((addr,self.source[addr]) for addr in self.order if addr)
        self.phase_at_start=startup["phase_at_start"]
        self.events={name:[] for name in EVENTS}
        self.identities_by_event={name:[] for name in IDENTITY_FIELDS}

    def record(self,name,*identity):
        self.events[name].append(self.cycle)
        if identity:
            self.identities_by_event[name].append(identity)

    def reserve(self,page,pair):
        slots=[]
        for group in range(2*pair,min(2*pair+2,25)):
            side=(group&1)^1
            slot=Slot(side,self.next_slot[side],page.tile,group,self.slot_sequence,self.layout)
            self.slot_sequence+=1
            assert all(s.index!=slot.index for s in self.slots[side])
            self.slots[side].append(slot)
            self.next_slot[side]=(slot.index+1)%self.layout.limits[side]
            self.ring_peak[side]=max(self.ring_peak[side],len(self.slots[side]))
            slots.append(slot)
        return tuple(slots)

    def phase(self):
        return (self.cycle-self.kickoff+self.phase_at_start)&1

    def unit_readiness(self, tile, pair):
        weights = self.layout.sizes[tile] - (0 if pair == 12 else 128)
        inputs = min((pair + 1) * 256, 3168)
        return weights, inputs

    def input_ready_for_issue(self, tile, pair, k):
        return True

    def start_unit(self):
        if self.cycle<=self.kickoff:
            return "prelude"
        reasons=[]
        for tile in range(self.oldest,min(self.oldest+2,len(self.layout.widths))):
            page=self.pages[tile%2]
            if page is None or page.tile!=tile or page.next_unit==13:
                continue
            pair=page.next_unit
            older=self.pages[self.oldest%2]
            if tile>self.oldest and older is not None and older.next_unit<13:
                gap=min((older.next_unit+1)*256,3168)-self.input_written
                if 0<gap<(64 if pair==12 else 128):
                    continue
            weight_need, input_need = self.unit_readiness(tile, pair)
            if page.written < weight_need:
                reasons.append("weight_page")
                continue
            if self.input_written < input_need:
                reasons.append("input_prefix")
                continue
            full=[side for side in ((1,) if pair==12 else (0,1))
                  if len(self.slots[side])==self.layout.limits[side]]
            if full:
                self.blocked_sides.update(full)
                reasons.append("result_slots")
                continue
            if pair!=12 and self.phase():
                reasons.append("pair_phase")
                continue
            page.next_unit+=1
            self.unit=base.Unit(page,pair,self.reserve(page,pair))
            self.unit_history.append([self.cycle,tile,pair])
            self.early_switches+=tile>self.oldest
            return None
        return reasons[0] if reasons else "weight_page_or_pipeline"

    def issue(self, ports):
        self.blocked_sides.clear()
        if self.unit is None:
            reason=self.start_unit()
            if reason:
                self.stats["issue_wait_"+reason]+=1
                return
        unit=self.unit
        paired=unit.pair!=12
        index=unit.index
        slot=unit.slots[index%2] if paired else unit.slots[0]
        k=index//2 if paired else index
        width=slot.width
        tomorrow=self.quant.get(self.cycle+1)
        rows=range(4*slot.group,min(4*slot.group+4,99))
        cells=[base.input_location(row,k) for row in rows]
        reason=None
        if unit.page.written<width+width//4+(width//2)*(k+1):
            reason="weight_vector"
        elif not self.input_ready_for_issue(slot.tile, unit.pair, k):
            reason = "input_vector"
        elif not paired and k==63 and self.phase():
            reason="tail_phase"
        elif any(bank in ports for bank,_ in cells):
            reason="input_quant_bank"
        elif paired and not index%2 and (self.phase() or (tomorrow and tomorrow[0].side==1)):
            reason="pair_bank_or_phase"
        if reason:
            self.stats["issue_wait_"+reason]+=1
            return
        values=[]
        for row,(bank,address) in zip(rows,cells):
            stored,value=self.input_banks[bank][address]
            assert stored==row
            values.append(value)
            ports.add(bank)
        self.tokens[self.cycle%64]=base.Token(slot,k,tuple(values),not paired or not index%2)
        self.max_last_issue=self.cycle
        self.issue_count+=1
        self.stats["input_macro_reads"]+=len(values)
        unit.index+=1
        if unit.index==unit.length:
            self.unit=None
        self.record("issue",slot.tile,unit.pair,index)

    def mac(self):
        weight_ports=set()
        for col in range(self.layout.stride):
            age=1+2*col
            read=self.tokens[(self.cycle-age)%64] if self.cycle>=age else None
            execute=self.tokens[(self.cycle-age-1)%64] if self.cycle>age else None
            if execute and col<execute.slot.width:
                self.marks.setdefault("first_mac",self.cycle)
                slot,k=execute.slot,execute.inner
                page=self.pages[slot.tile%2]
                assert page is not None and page.tile==slot.tile
                tile,inner,w=self.weight_q[col]
                assert (tile,inner)==(slot.tile,k)
                context=self.acc[slot.group%2]
                results=[]
                for row,x in enumerate(execute.values):
                    key=(row,col)
                    prior=context.get(key)
                    if k==0:
                        assert prior is None
                        value=page.bias[col]+x*w
                    else:
                        assert prior[:2]==(slot.sequence,k)
                        value=prior[2]+x*w
                    value=base.baseline.q16.signed(value,36)
                    self.mac_operations+=1
                    if k==63:
                        results.append(base.baseline.q16.rne(value,page.shift[col]))
                        del context[key]
                    else:
                        context[key]=(slot.sequence,k+1,value)
                if results:
                    when=self.cycle+2
                    assert when not in self.quant
                    self.quant[when]=slot,col,tuple(results)
            if read and col<read.slot.width and read.weight_read:
                address=64*(read.slot.tile%2)+read.inner
                value=self.weight_banks[col][address]
                assert value[:2]==(read.slot.tile,read.inner)
                self.weight_q[col]=value
                weight_ports.add(col)
        self.stats["weight_macro_reads"]+=len(weight_ports)
        return weight_ports

    def finish_output_column(self,ports):
        event=self.quant.pop(self.cycle,None)
        if event is None:
            return
        slot,col,values=event
        assert col==slot.columns
        for row,value in enumerate(values):
            bank,address=slot.cell(row,col)
            assert bank not in ports and self.input_banks[bank][address] is None
            self.input_banks[bank][address]=slot.sequence,value
            ports.add(bank)
        slot.columns+=1
        self.stats["quant_halfwords"]+=len(values)
        self.marks["last_emit"]=self.cycle
        if slot.columns==slot.width:
            slot.completed_edge=self.cycle
            self.pages[slot.tile%2].emitted+=1
        self.record("quant",col,slot.side)

    def load_private(self,ports,weight_ports):
        if not self.incoming:
            return
        addr,data=self.incoming[0]
        if addr<3168:
            assert addr==self.input_written and self.weight_pack is None
            rows=self.identities[2*addr:2*addr+2]
            cells=[base.input_location(row,k) for row,k in rows]
            assert cells[0][0]!=cells[1][0]
            if any(bank in ports for bank,_ in cells):
                self.stats["input_write_wait"]+=1
                return
            for (row,_),(bank,offset),value in zip(rows,cells,base.halves(data)):
                assert self.input_banks[bank][offset] is None
                self.input_banks[bank][offset]=row,value
                ports.add(bank)
            self.input_written+=1
        else:
            tile,offset=self.layout.param(addr)
            width=self.layout.widths[tile]
            page=self.pages[tile%2]
            assert page.tile==tile
            header=width+width//4
            if offset<width:
                assert page.written==offset
                page.bias[offset]=base.baseline.q16.signed(data,32)
                page.written+=1
            elif offset<header:
                assert page.written==offset
                col=4*(offset-width)
                page.shift[col:col+4]=[base.baseline.q16.signed((data>>(8*i))&255,8) for i in range(4)]
                page.written+=1
            elif self.weight_pack is None:
                assert page.written==offset
                self.weight_pack=addr,data
            else:
                saved_addr,saved_data=self.weight_pack
                assert addr==saved_addr+1 and page.written==offset-1
                k,pair=divmod(offset-1-header,width//2)
                banks=range(2*pair,2*pair+4)
                if any(bank in weight_ports for bank in banks):
                    self.stats["weight_write_wait"]+=1
                    return
                for bank,value in zip(banks,base.halves(saved_data)+base.halves(data)):
                    self.weight_banks[bank][64*(tile%2)+k]=tile,k,value
                page.written+=2
                self.weight_pack=None
                self.stats["weight_write64"]+=1
                weight_ports.update(banks)
                if page.written==self.layout.sizes[tile]:
                    self.page_history.append([tile,self.cycle])
        self.incoming.popleft()
        self.record("load")

    def prefetch_output(self, ports):
        if len(self.out_held)==2:
            return
        options=[]
        for ring in self.slots:
            slot=next((slot for slot in ring if slot.reads<slot.words),None)
            if slot is None or slot.completed_edge is None or slot.completed_edge==self.cycle:
                continue
            row,pair=divmod(slot.reads,slot.width//2)
            cells=[slot.cell(row,2*pair+i) for i in range(2)]
            if any(bank in ports for bank,_ in cells):
                self.stats["result_read_bank_conflict"]+=1
                continue
            options.append((slot,row,pair,cells))
        if not options:
            return
        slot,row,pair,cells=min(options,key=lambda item:(item[0].side not in self.blocked_sides,item[0].sequence))
        values=[]
        for bank,address in cells:
            owner,value=self.input_banks[bank][address]
            assert owner==slot.sequence
            values.append(value)
            ports.add(bank)
        index=(4*slot.group+row)*256+self.layout.stride*slot.tile+2*pair
        assert tuple(values)==tuple(self.golden[index:index+2]),(self.case,self.cycle,index)
        self.out_pending=slot,index,base.packed(*values)
        slot.reads+=1
        self.stats["result_macro_reads"]+=2
        self.record("scratch",slot.side)

    def write_shared(self,packet):
        slot,index,data=packet
        addr=base.RESULT_BASE+index//2
        assert addr not in self.out_memory and addr not in self.shared
        self.out_memory[addr]=data
        slot.committed+=1
        self.output_written+=1
        self.marks.setdefault("first_physical_commit",self.cycle)
        self.marks["final_physical_commit"]=self.cycle
        if slot.committed==slot.words:
            assert slot.reads==slot.words and self.slots[slot.side].popleft() is slot
            for row in range(slot.words//(slot.width//2)):
                for col in range(slot.width):
                    bank,address=slot.cell(row,col)
                    assert self.input_banks[bank][address][0]==slot.sequence
                    self.input_banks[bank][address]=None

    def next_source(self):
        if self.cycle<=self.kickoff or self.read_index==11680:
            return None
        if len(self.incoming)+int(self.bus_pending is not None)>=2:
            return None
        addr=self.order[self.read_index]
        if addr not in self.shared:
            self.stats["dma_wait_host_word"]+=1
            return None
        if addr>=base.PARAMETER_BASE:
            tile,offset=self.layout.param(addr)
            page=self.pages[tile%2]
            if (page is not None and page.tile!=tile) or tile>self.oldest+1:
                self.stats["dma_wait_page_release"]+=1
                return None
            assert page is not None or offset==0
        return addr

    def transfer(self,ports):
        previous=self.bus_pending
        bankset=set()
        cpu_busy=self.cycle in self.cpu_reserved
        setup=self.cpu_setup.get(self.cycle)
        if setup:
            addr=(setup["accept_addr"]-base.baseline.t.BASE)//4
            bankset.add(base.physical_bank(addr))
        source=self.next_source() if not cpu_busy else None
        self.bus_pending=None
        if source is not None:
            bankset.add(base.physical_bank(source))
            self.bus_pending=source,self.shared[source]
            self.read_index+=1
            if source>=base.PARAMETER_BASE:
                tile,offset=self.layout.param(source)
                if offset==0:
                    page=base.Page(tile)
                    page.bias=[None]*self.layout.stride
                    page.shift=[None]*self.layout.stride
                    self.pages[tile%2]=page
            self.record("source_fire",0xa0000000+4*source)
        host_dual=False
        if self.host_index<len(self.host_order) and self.cycle>=self.host_start:
            addr,data=self.host_order[self.host_index]
            bank=base.physical_bank(addr)
            if (not cpu_busy and previous is None and source is None) or (
                    source is not None and bank not in bankset):
                assert bank not in bankset and addr not in self.out_memory
                bankset.add(bank)
                if addr in self.source:
                    assert addr not in self.shared
                    self.stats["host_payload_commits"]+=1
                    self.marks.setdefault("first_host_physical_commit",self.cycle)
                else:
                    self.stats["host_setup_commits"]+=1
                self.shared[addr]=data
                self.host_index+=1
                host_dual=source is not None
                self.stats["host_dual"]+=host_dual
                self.record("host",addr)
            else:
                self.stats["host_wait_"+("same_bank" if source is not None else "owner")]+=1
        if previous:
            self.incoming.append(previous)
            self.record("source_return")
        self.transfer_results(ports, bankset, host_dual)
        self.read_peak=max(self.read_peak,len(self.incoming)+int(source is not None))
        self.output_credit_peak=max(self.output_credit_peak,len(self.out_held)+int(self.out_pending is not None))
        assert self.read_peak<=2 and self.output_credit_peak<=2
        self.stats["shared_bank_accesses_"+str(len(bankset))]+=1

    def transfer_results(self, ports, bankset, host_dual):
        if self.write_ack is not None:
            assert self.write_ack==self.cycle-1
            self.stats["write_ack"]+=1
            self.write_ack=None
            self.record("ack")
            if self.stats["write_ack"]==12672:
                self.marks["final_ack"]=self.cycle
        pending=self.out_pending
        self.out_pending=None
        if self.out_held:
            packet=self.out_held[0]
            bank=base.physical_bank(base.RESULT_BASE+packet[1]//2)
            assert 4<=bank<=7
            if bank not in bankset:
                bankset.add(bank)
                self.out_held.popleft()
                self.write_shared(packet)
                self.write_ack=self.cycle
                self.record("write",base.RESULT_BASE+packet[1]//2)
                if host_dual:
                    self.record("triple")
            else:
                self.stats["result_shared_bank_wait"]+=1
        if pending:
            self.out_held.append(pending)
        self.prefetch_output(ports)

    def retire_pages(self):
        if self.oldest==len(self.layout.widths):
            return
        page=self.pages[self.oldest%2]
        if page is not None and page.tile==self.oldest and page.emitted==25:
            assert page.next_unit==13 and page.written==self.layout.sizes[page.tile]
            self.pages[self.oldest%2]=None
            self.record("page_release",self.oldest)
            self.oldest+=1

    def run(self):
        self.weight_banks=[[None]*128 for _ in range(self.layout.stride)]
        self.weight_q=[None]*self.layout.stride
        self.acc=[{},{}]
        last_progress=-1
        last_cycle=0
        while "final_ack" not in self.marks:
            self.tokens[self.cycle%64]=None
            ports=set()
            self.finish_output_column(ports)
            self.issue(ports)
            weight_ports=self.mac()
            self.load_private(ports,weight_ports)
            self.transfer(ports)
            self.retire_pages()
            progress=sum(len(self.events[name]) for name in ("host","source_fire","load","issue","quant","scratch","write"))
            if progress!=last_progress:
                last_progress=progress
                last_cycle=self.cycle
            if self.cycle-last_cycle>128:
                return self.summary(False)
            self.cycle+=1
        assert self.host_index==11690 and self.read_index==11680 and self.input_written==3168
        assert self.issue_count==len(self.layout.widths)*1600
        assert self.mac_operations==25344*64 and self.stats["weight_write64"]==4096
        assert self.stats["quant_halfwords"]==self.stats["result_macro_reads"]==25344
        assert self.stats["weight_macro_reads"]==212992 and self.output_written==12672
        assert not any(self.slots) and self.oldest==len(self.layout.widths)
        for index in range(0,25344,2):
            assert base.halves(self.out_memory[base.RESULT_BASE+index//2])==tuple(self.golden[index:index+2])
        return self.summary(True)


def observation():
    with OBSERVATION.open(newline="") as stream:
        rows=list(csv.DictReader(stream))
    edges={name:[int(row["cycle"]) for row in rows if
            ((row["host_valid"],row["host_ready"])==("1","1") if name=="host" else row[name]=="1")]
            for name in EVENTS}
    identities={name:[tuple(int(rows[edge][field]) for field in fields) for edge in edges[name]]
                for name,fields in IDENTITY_FIELDS.items()}
    start_row,=[row for row in rows if row["mmio_start"]=="1"]
    start=int(start_row["cycle"])
    host_controls=[(int(row["host_addr"]),0) for row in rows
                   if row["host_valid"]==row["host_ready"]=="1" and 2<int(row["cycle"])<13]
    assert len(host_controls)==10
    cpu=[]
    for row in rows:
        if row["cpu_fire"]=="1":
            edge=int(row["cycle"])
            rsp=next(int(r["cycle"]) for r in rows[edge+1:] if r["cpu_rsp"]=="1")
            cpu.append(dict(accept=edge,response=rsp,accept_addr=int(row["cpu_addr"])))
    cpu.append(dict(accept=0,response=1,accept_addr=0xa007ff00))
    return dict(controls=host_controls,start=start,host_start=0,phase_at_start=int(rows[start+1]["phase"])^1,
                cpu_setup=cpu),edges,identities


def run_case(args):
    case,width,startup=args
    return Task(case,width,startup).run()


def main():
    startup,actual,identities=observation()
    task=Task(0,16,startup)
    baseline=task.run()
    compare={}
    for name,observed in actual.items():
        predicted=task.events[name]
        first=next(((a,b) for a,b in zip(predicted,observed) if a!=b),None)
        compare[name]=dict(model_count=len(predicted),native_count=len(observed),
                           first_different_edge=first,matching_edges=len(set(predicted)&set(observed)))
    identity_match={name:task.identities_by_event[name]==values for name,values in identities.items()}
    assert all(identity_match.values()), identity_match
    program, _, _, _ = base.baseline.observe()
    legacy_start=next(row["accept"] for row in program if row["bus"]=="cpu"
                      and row["address"]==0x48 and not row["read"])
    legacy_replay=Task(0,16,dict(startup,start=legacy_start)).run()
    calibration=dict(identity_match=identity_match,model=baseline,startup=startup,event_comparison=compare,
                     legacy_start_counterfactual=dict(start_edge=legacy_start,
                         cold_cycles=legacy_replay["cold_cycles"],
                         first_mac=legacy_replay["first_mac"],
                         last_emit=legacy_replay["last_emit"],
                         final_write=legacy_replay["final_physical_commit"]),
                     native_last_write=actual["write"][-1],native_last_ack=actual["ack"][-1],
                     exact_all_edges=all(task.events[k]==v for k,v in actual.items()))
    (REPORT/"calibration.json").write_text(json.dumps(calibration,indent=2)+"\n")
    print("M0",baseline["cold_cycles"],calibration["exact_all_edges"],compare,flush=True)
    assert calibration["exact_all_edges"], compare
    if "--calibrate" in sys.argv:
        return
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(run_case,((case,20,startup) for case in range(12))))
    if all(row["complete"] for row in rows):
        total=sum(row["cold_cycles"] for row in rows)
        throughput=1_800_000_000/total
    else:
        total=None
        throughput=None
    result=dict(cycles_total=total,throughput=throughput,target_passed=total is not None and total<300000,
                exact_calibration=calibration["exact_all_edges"],rows=rows)
    (REPORT/"model-result.json").write_text(json.dumps(result,indent=2)+"\n")
    print("M20",total,throughput,[r["cold_cycles"] for r in rows],flush=True)


if __name__=="__main__":
    main()
