"""Three-row, one-stage operand pipeline using the observed SR CPU cadence."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT/'reports/optimization/ffn_sr_r3o'
sys.path.insert(0,str(ROOT/'scripts/sr_pr1'))
import model_screen as sr
from model import Core, rne, signed, vectors


class ResultQueue:
    """Five single-port SRAMs, one register FIFO and the existing two-word return."""
    def reset(self):
        self.fifo = deque()
        self.rows = [deque() for _ in range(3)]
        self.held, self.pending = [], []
        self.pending_row = 0
        self.retired = 0
        self.peak = [0,0,0,0]
        self.blocked = [0,0,0]

    def comb(self, item, push, push_row, single, paired):
        pop = 2 if paired and len(self.held)==2 else int(bool(single and self.held))
        next_item = item + len(self.held) + len(self.pending)
        next_row = (next_item//256)%3
        captured = len(self.pending)
        available = [len(row) for row in self.rows]
        row0_count = available[0] + (captured if self.pending_row==0 else 0)
        drain = bool(self.fifo and row0_count<128)
        if next_row==0 and available[0] and next_item<25344:
            if 2-len(self.held)-captured+pop:
                drain=False
        room = len(self.fifo)+2<=16+int(drain) if push_row==0 else available[push_row]+2<=256
        accept = push and room
        space = 2-len(self.held)-captured+pop
        read = 0
        if next_item<25344 and space and available[next_row] and not (accept and push_row!=0 and push_row==next_row):
            read = 2 if next_row and space>=2 and available[next_row]>=2 and next_item%256!=255 else 1
        return dict(pop_count=pop,read=read,next_row=next_row,drain=drain,ready=room,
                    accept=accept,push_row=push_row,blocked=push and not room)

    def tick(self, control, pair, restart=False):
        if restart:
            self.reset()
            return []
        pop=control['pop_count']
        popped=self.held[:pop]
        for index,_ in popped:
            if index!=self.retired:
                raise RuntimeError('Retirement out of order')
            self.retired+=1
        self.held=self.held[pop:]+self.pending
        self.pending=[self.rows[control['next_row']].popleft() for _ in range(control['read'])]
        self.pending_row=control['next_row']
        if control['drain']:
            self.rows[0].append(self.fifo.popleft())
        row=control['push_row']
        if control['accept']:
            (self.fifo if row==0 else self.rows[row]).extend(pair)
        self.blocked[row]+=int(control['blocked'])
        counts=[len(self.fifo)]+[len(row)+(len(self.pending) if i==self.pending_row else 0)
                                 for i,row in enumerate(self.rows)]
        if any(size>limit for size,limit in zip(counts,(16,128,256,256))):
            raise RuntimeError('Physical result capacity exceeded')
        self.peak=[max(a,b) for a,b in zip(counts,self.peak)]
        return popped


text=inspect.getsource(Core)
for old,new in (
    ('class Core:', 'class Row3Core:'),
    ('OutputQueue()', 'ResultQueue()'),
    ('[0] * 16', '[0] * 48'),('range(16)','range(48)'),
    ('(1 if self.row == 98 else 2)','3'),('(self.row + 4)','(self.row + 6)'),
    ('self.row < 98 or self.tile < 31','self.row < 96 or self.tile < 15'),
    ('bool(self.emit_row or self.row == 98)','self.emit_row == 2'),
    ('        next_row1 = self.row < (96 if self.tile == 31 else 98)\n',''),
    ('divmod(lane, 8)','divmod(lane, 16)'),(' and (r == 0 or self.row < 98)',''),
    (' and (r == 0 or next_row1)',''),('int(self.state == 7)','int(self.state == 7 and self.inner >= 0)'),
    ('self.emit_row * 8','self.emit_row * 16'),('self.tile * 8','self.tile * 16'),
    ('target_tile * 8','target_tile * 16'),('lane % 8','lane % 16'),('lane // 8','lane // 16'),
    ('% 32','% 16'),('self.lane == 6','self.lane == 14'),('self.lane < 6','self.lane < 14'),
    ('self.chunk == 3','self.chunk == 7'),('self.tile < 31','self.tile < 15'),
    ('self.state == 7 and self.inner < 63','self.state == 7 and self.inner < 62'),
    ('self.emit_row = 1','self.emit_row += 1'),('self.row == 98','self.row == 96'),('self.row += 2','self.row += 3'),
    ('            self.state = 7\n','            self.inner, self.state = -1, 7\n'),
    ('                    self.state = 3\n','                    self.inner, self.state, self.seed_ready = 0, 6, 0\n'),
):
    if old not in text:
        raise RuntimeError('Frozen model shape changed: '+old)
    text=text.replace(old,new)
exec(compile(text,str(Path(__file__)),'exec'))


def program(commands):
    """Preserve the observed MMIO gaps and replace only the row-group loop."""
    prefix=commands[:11]
    first, second, result, later = (commands[start:start+4] for start in (11,15,19,23))
    out=list(prefix)
    def transfer(template, address, size, direction):
        for cmd,value in zip(template,(address,size,direction,0)):
            out.append(dict(cmd,data=value))
    transfer(first,0xa0000000,96,1)
    for group in range(33):
        if group<32:
            transfer(second if group==0 else later,0xa0000000+384*(group+1),96,1)
        transfer(result,0xa0010000+1536*group,384,2)
    return out


def simulate(case,prefix,commands,prior_response):
    image, expected=sr.frozen_image(case)
    wrapper=sr.WriteWrapper()
    core=wrapper.core=Row3Core(layer=case)
    memory=wrapper.memory
    for sample in prefix:
        row=dict(sample)
        if row['host_cmd_valid'] and not row['host_cmd_read'] and row['host_cmd_addr'] in image:
            row['host_cmd_wdata']=image[row['host_cmd_addr']]
        memory.context(row)
        cpu=sr.cpu_request(row)
        wrapper.tick(cpu,wrapper.comb(cpu),row['cycle'])
    due=prior_response+commands[0]['gap']
    index=retired=mac=fill=0
    accepted=False
    first_mac=commit=ack=None
    for cycle in range(prefix[-1]['cycle']+1,160000):
        memory.context(sr.empty_external())
        cpu=sr.idle_cpu()
        if index<len(commands) and not accepted and cycle>=due:
            cpu.update({key:commands[index][key] for key in ('read','address','data','mask')})
            cpu['valid']=1
        c=wrapper.comb(cpu)
        if cpu['valid'] and c['cpu_ready']:
            accepted=True
        if accepted and c['cpu_valid']:
            accepted=False
            index+=1
            if index<len(commands):
                due=cycle+commands[index]['gap']
        if core.state==7:
            fill+=int(core.inner<0)
            mac+=int(core.inner>=0)
            if first_mac is None and core.inner>=0:
                first_mac=cycle
        was_active=wrapper.engine.pd_active
        for identity,value in wrapper.tick(cpu,c,cycle):
            if identity!=retired or expected[retired]!=value:
                raise RuntimeError('Golden result differs at index %d'%retired)
            retired+=1
        if memory.writes==12672 and commit is None:
            commit=memory.commits[-1][0]
            for i,(_,address,data) in enumerate(memory.commits):
                packed=(expected[2*i]&65535)|((expected[2*i+1]&65535)<<16)
                if address!=0xa0010000+4*i or data!=packed:
                    raise RuntimeError('Physical write mismatch at word %d'%i)
        if commit is not None and was_active and not wrapper.engine.pd_active:
            ack=cycle
            break
    totals=(memory.host_writes,memory.reads,memory.writes,wrapper.engine.launches,retired,mac,fill)
    if totals!=(11946,11936,12672,68,25344,33792,528) or ack is None or ack<=commit:
        raise RuntimeError('Cold task does not meet the physical schedule: %s'%(totals,))
    return dict(case=case+1,cold_cycles=commit+1,first_mac=first_mac,final_commit=commit,
                final_ack=ack,host_writes=totals[0],dma_reads=totals[1],dma_writes=totals[2],
                descriptors=totals[3],ordered_outputs=retired,mac_cycles=mac,fill_cycles=fill,
                peak=core.queue.peak,quant_stall=core.queue.blocked)


def main():
    prefix,commands,prior,_=sr.read_program()
    commands=program(commands)
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(simulate,i,prefix,commands,prior) for i in range(12)]
        results=[]
        for job in jobs:
            row=job.result()
            results.append(row)
            print('R3O_MODEL',row,flush=True)
    total=sum(row['cold_cycles'] for row in results)
    (REPORT/'model-results.json').write_text(json.dumps(dict(results=results,cycles_total=total,
        throughput=1800000000/total,model_passed=total<1185396,
        cpu_pacing='SR native case1 response gaps adapted to three-row descriptors',
        measured_hardware=False),indent=2)+'\n')

if __name__=='__main__':
    main()
