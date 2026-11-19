"""One fixed four-row core and one fixed weight-term-serial core; Python models only."""
from common import Core,OutputQueue,signed,rne,arrays


class FourRowQueue:
    def __init__(self):self.reset()

    def reset(self):
        self.fifo=[None]*16
        self.fifo_count=self.fifo_read=self.fifo_write=0
        self.rows=[[None]*(128 if r==0 else 256) for r in range(4)]
        self.counts=[0]*4;self.reads=[0]*4;self.writes=[0]*4
        self.held=[];self.pending=[];self.pending_row=0;self.retired=0
        self.peak=dict(fifo=0,row0=0,row1=0,row2=0,row3=0,total=0)

    def comb(self,item,push_valid,push_row,out_ready,out_pair_ready):
        h,p=len(self.held),len(self.pending)
        pop=2 if out_pair_ready and h==2 else 1 if out_ready and h else 0
        capture=[p if self.pending_row==r else 0 for r in range(4)]
        row_push=bool(push_valid and push_row!=0 and self.counts[push_row]+2<=256+capture[push_row])
        space=2-h-p+pop;next_item=item+h+p;row=(next_item//256)%4
        read=bool(space and next_item<25344 and self.counts[row]>capture[row] and not(row_push and row==push_row))
        issue=2 if read and row!=0 and space>=2 and next_item%256!=255 and self.counts[row]>=capture[row]+2 else int(read)
        drain0=bool(self.fifo_count and self.counts[0]<128 and not(read and row==0))
        room0=self.fifo_count+2<=16+int(drain0)
        return dict(pop_count=pop,capture=capture,read_row=row,read=read,issue=issue,
                    drain0=drain0,row_push=row_push,push_row=push_row,
                    row0_push=bool(push_valid and push_row==0 and room0),
                    ready=bool(self.counts[push_row]+2<=256+capture[push_row]) if push_row else room0)

    def tick(self,c,pair,restart=False):
        if restart:self.reset();return []
        popped=self.held[:c['pop_count']]
        for token in popped:
            if token is None or token[0]!=self.retired:raise RuntimeError('Four-row output identity/order mismatch')
            self.retired+=1
        held=self.held[c['pop_count']:]+self.pending
        pending=[]
        ports=[]
        if c['read']:
            r=c['read_row'];depth=len(self.rows[r]);address=(self.reads[r]+c['capture'][r])%depth
            pending=[self.rows[r][(address+i)%depth] for i in range(c['issue'])]
            ports.extend([6] if r==0 else [2*(r-1)+(address+i)%2 for i in range(c['issue'])])
        drained=self.fifo[self.fifo_read] if c['drain0'] else None
        if c['row0_push']:
            for i,t in enumerate(pair):self.fifo[(self.fifo_write+i)%16]=t
            self.fifo_write=(self.fifo_write+2)%16
        if c['drain0']:
            self.rows[0][self.writes[0]]=drained
            self.writes[0]=(self.writes[0]+1)%128;self.fifo_read=(self.fifo_read+1)%16
            ports.append(6)
        if c['row_push']:
            r=c['push_row']
            for i,t in enumerate(pair):self.rows[r][(self.writes[r]+i)%256]=t
            self.writes[r]=(self.writes[r]+2)%256
            ports.extend([2*(r-1),2*(r-1)+1])
        if len(ports)!=len(set(ports)):raise RuntimeError('Four-row output bank port conflict')
        self.fifo_count+=2*int(c['row0_push'])-int(c['drain0'])
        for r in range(4):
            self.counts[r]+=(int(c['drain0']) if r==0 else 2*int(c['row_push'] and c['push_row']==r))-c['capture'][r]
            self.reads[r]=(self.reads[r]+c['capture'][r])%len(self.rows[r])
        self.held,self.pending=held,pending
        self.pending_row=c['read_row'] if c['read'] else 0
        for key,value in [('fifo',self.fifo_count)]+[('row%d'%r,self.counts[r]) for r in range(4)]+[('total',self.fifo_count+sum(self.counts)+len(self.held))]:
            self.peak[key]=max(self.peak[key],value)
        self.last_ports=ports
        return popped

    def snapshot(self):
        return dict(fifo_count=self.fifo_count,row0_count=self.counts[0],row1_count=sum(self.counts[1:]),
                    held_count=len(self.held),pending_count=len(self.pending),pending_row1=int(self.pending_row!=0))


class CoreA(Core):
    def __init__(self,initial_state=1,layer=0,numeric=True):
        super().__init__(initial_state=initial_state,layer=layer,numeric=numeric)
        self.queue=FourRowQueue()

    def valid_rows(self):return min(4,99-self.row)
    def complete(self):return self.input_count>=(self.row+self.valid_rows())*64

    def input_read(self):
        return (self.state==6 and self.complete()) or (self.state==7 and self.inner<63)

    def capacity(self,kind):
        return (self.state==2 and kind in [1,5]) or (kind==0 and self.state>=3 and self.input_count<6336 and self.input_count<(self.row+8)*64 and not self.input_read())

    def comb(self,inp):
        q=self.queue.comb(self.item,self.state==8,self.emit_row,inp.get('out_ready',False),inp.get('out_pair_ready',False))
        quant=bool(self.state==8 and q['ready'])
        has_next=self.row<96 or self.tile<63
        last_emit=self.emit_row==self.valid_rows()-1
        next_rows=min(4,99-self.row-(4 if self.tile==63 else 0))
        sm=mm=0
        for lane in range(16):
            r,col=divmod(lane,4)
            seed=(self.state==5 and self.chunk==col//2 and r<self.valid_rows()) or (quant and has_next and self.emit_row==r and self.lane//2==col//2 and r<next_rows)
            sm|=int(seed)<<lane;mm|=int(self.state==7 and r<self.valid_rows())<<lane
        return dict(q=q,quant=quant,seed_mask=sm,mac_mask=mm,has_next=has_next,last_emit=last_emit)

    def tick(self,inp,c):
        if inp.get('reset'):self.reset();return []
        pair=[]
        if c['quant']:
            for lane in [self.emit_row*4+self.lane,self.emit_row*4+self.lane+1]:
                if self.products[lane]!=64 or self.seeds[lane]!=1:raise RuntimeError('Four-row contribution count mismatch')
                index=(self.row+self.emit_row)*256+self.tile*4+lane%4
                value=rne(self.acc[lane],self.shifts[index%256]) if self.numeric else 0
                pair.append((index,value));self.products[lane]=self.seeds[lane]=0;self.quantized+=1
        popped=self.queue.tick(c['q'],pair,inp.get('layer_start',False))
        for lane in range(16):
            if c['seed_mask']>>lane&1:
                tile=self.tile if self.state==5 else (self.tile+1)%64
                self.acc[lane]=signed(self.bias[tile*4+lane%4],36) if self.numeric else 0
                self.seeds[lane]+=1
            elif c['mac_mask']>>lane&1:
                if self.numeric:self.acc[lane]=signed(self.acc[lane]+self.x[(self.row+lane//4)*64+self.inner]*self.w[self.inner*256+self.tile*4+lane%4],36)
                self.products[lane]+=1
        state,seed,complete=self.state,self.seed_ready,self.complete()
        if inp.get('layer_start'):self.seed_ready=0
        else:
            if state==3 and seed:self.seed_ready=0
            if c['quant'] and c['has_next'] and c['last_emit'] and self.lane==2:self.seed_ready=1
        if state==0:self.state=1
        elif state==1 and inp.get('start'):self.parameter_count=self.shift_count=0;self.state=2
        elif state==2 and inp.get('layer_start'):
            self.row=self.tile=self.item=self.lane=self.inner=self.emit_row=0;self.state=15
        elif state==15 and complete:self.state=3
        elif state==3:
            self.chunk=0
            if seed:self.inner,self.state=0,6
            else:self.state=4
        elif state==4:self.state=5
        elif state==5:
            if self.chunk==1:self.inner,self.state=0,6
            else:self.chunk+=1;self.state=4
        elif state==6 and complete:self.state=7
        elif state==7:
            if self.inner==63:self.lane=self.emit_row=0;self.state=8
            else:self.inner+=1
        elif state==8 and c['quant']:
            if not c['last_emit']:self.emit_row+=1
            else:
                self.emit_row=0
                if self.lane<2:self.lane+=2
                elif self.tile<63:self.tile+=1;self.state=3
                else:self.state=14
        elif state==14:
            if self.row==96:self.state=12
            else:self.row+=4;self.tile=self.lane=0;self.state=15
        if inp.get('load'):
            name={0:'input_count',1:'parameter_count',5:'shift_count'}[inp['load_kind']]
            if inp['load_address']!=getattr(self,name):raise RuntimeError('Four-row load prefix mismatch')
            setattr(self,name,getattr(self,name)+(2 if inp.get('load_pair') and inp['load_kind']!=5 else 1))
        if c['q']['pop_count']:
            if self.item+c['q']['pop_count']==25344:
                self.state=0;self.input_count=self.parameter_count=self.shift_count=0
            else:self.item+=c['q']['pop_count']
        return popped


class CoreC(Core):
    def __init__(self,initial_state=1,layer=0,numeric=True):
        super().__init__(initial_state=initial_state,layer=layer,numeric=numeric)
        self.phase=0
        weights=arrays(layer)[1]
        self.steps=[[1+max(1,max(abs(int(v)).bit_count() for v in weights[k,t*8:t*8+8])) for t in range(32)] for k in range(64)]

    def reset(self):
        super().reset();self.phase=0

    def last_phase(self):return self.phase==self.steps[self.inner][self.tile]-1

    def input_read(self):
        return (self.state==6 and self.complete()) or (self.state==7 and self.inner<63 and self.last_phase())

    def capacity(self,kind):
        return (self.state==2 and kind in [1,5]) or (kind==0 and self.state>=3 and self.input_count<6336 and self.input_count<(self.row+4)*64 and not self.input_read())

    def comb(self,inp):
        c=super().comb(inp)
        if self.state==7 and not self.last_phase():c['mac_mask']=0
        return c

    def tick(self,inp,c):
        if self.state!=7 or self.last_phase() or inp.get('reset'):
            result=super().tick(inp,c)
            self.phase=0
            return result
        popped=self.queue.tick(c['q'],[],False)
        if inp.get('load'):
            if inp['load_kind']!=0 or inp['load_address']!=self.input_count:raise RuntimeError('Serial-core load identity mismatch')
            self.input_count+=1
        self.item+=c['q']['pop_count']
        self.phase+=1
        return popped
