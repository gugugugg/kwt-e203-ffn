"""Independent cycle model of IR's single DMA, ICB ownership and local responder."""
from model import Core


class Memory:
    def __init__(self, core):
        self.pending = self.valid = 0
        self.data = 0
        self.storage = {0xa0000000 + i * 2: (core.x[i] & 65535) | ((core.x[i + 1] & 65535) << 16)
                        for i in range(0, len(core.x), 2)}
        self.reads = self.writes = 0
        self.commits = []

    def comb(self):
        return dict(ready=not self.pending and not self.valid, valid=self.valid, data=self.data)

    def tick(self, cmd, rsp_ready, cycle):
        c = self.comb()
        if self.valid and rsp_ready:
            self.valid = 0
        if self.pending:
            self.pending, self.valid = 0, 1
        if cmd['valid'] and c['ready']:
            self.pending = 1
            if cmd['read']:
                self.reads += 1
                self.data = self.storage.get(cmd['address'], 0)
            else:
                self.writes += 1
                self.storage[cmd['address']] = cmd['data']
                self.commits.append((cycle, cmd['address'], cmd['data']))


class Engine:
    def __init__(self):
        self.pd_active = self.output_transfer = 0
        self.address = 0xa003a100
        self.source_remaining = self.dest_remaining = self.pd_count = self.pd_valid = 0
        self.pd_write = self.pd_read = 0
        self.pd_source_slot = 1
        self.pd_source_pending = self.pd_dest_pending = 0
        self.slots = [0, 0]
        self.done = 1
        self.launches = 0

    def commands(self, input_ready, output_ready):
        memory_dest = self.pd_active and self.output_transfer and (self.pd_valid >> self.pd_read & 1)
        pio_dest = self.pd_active and not self.output_transfer and (self.pd_valid >> self.pd_read & 1) and not self.pd_dest_pending and input_ready
        memory_source = self.pd_active and not self.output_transfer and self.source_remaining != 0 and self.pd_count < 2
        pio_source = self.pd_active and self.output_transfer and self.source_remaining != 0 and not self.pd_source_pending and self.pd_count < 2 and output_ready
        return dict(memory=dict(valid=int(bool(memory_dest or memory_source)), read=int(not self.output_transfer),
                                address=self.address, data=self.slots[self.pd_read]),
                    pio=dict(valid=int(bool(pio_source or pio_dest)), read=int(bool(self.output_transfer)),
                             address=0x34 if self.output_transfer else 0x30, data=self.slots[self.pd_read], mask=15))

    def tick(self, commands, mem, pio, launch=None):
        if launch is not None:
            self.pd_active = int(launch['words'] != 0)
            self.done = int(launch['words'] == 0)
            self.output_transfer = launch['direction']
            self.address = launch['address']
            self.source_remaining = self.dest_remaining = launch['words']
            self.pd_count = self.pd_valid = self.pd_write = self.pd_read = 0
            self.pd_source_slot = self.pd_source_pending = self.pd_dest_pending = 0
            self.launches += 1
            return
        if not self.pd_active:
            return
        source, dest = (pio, mem) if self.output_transfer else (mem, pio)
        scmd, dcmd = (commands['pio'], commands['memory']) if self.output_transfer else (commands['memory'], commands['pio'])
        source_fire = bool(scmd['valid'] and source['ready'])
        source_complete = bool(source['valid'] and (self.pd_source_pending or source_fire))
        dest_fire = bool(dcmd['valid'] and dest['ready'])
        dest_complete = bool(dest['valid'] and (self.pd_dest_pending or dest_fire))
        source_pending = (self.pd_source_pending or source_fire) and not source_complete or self.pd_source_pending and source_complete and source_fire
        dest_pending = (self.pd_dest_pending or dest_fire) and not dest_complete or self.pd_dest_pending and dest_complete and dest_fire
        valid = self.pd_valid
        old_write, old_read = self.pd_write, self.pd_read
        if commands['memory']['valid'] and mem['ready']:
            self.address = (self.address + 4) & 0xffffffff
        if dest_fire:
            valid &= ~(1 << old_read)
            self.pd_read ^= 1
        if source_fire:
            self.source_remaining -= 1
            self.pd_source_slot = old_write
            self.pd_write ^= 1
        if source_complete:
            slot = self._old_source_slot if self.pd_source_pending else old_write
            self.slots[slot] = source['data']
            valid |= 1 << slot
        self.pd_count = (self.pd_count + int(source_fire) - int(dest_complete)) & 3
        self.pd_valid = valid
        self.pd_source_pending, self.pd_dest_pending = int(bool(source_pending)), int(bool(dest_pending))
        if dest_complete:
            self.dest_remaining -= 1
            if self.dest_remaining == 0:
                self.pd_active, self.done = 0, 1

    def remember(self):
        self._old_source_slot = self.pd_source_slot

    def snapshot(self):
        return {'dma_' + name: getattr(self, name) for name in [
            'pd_active', 'output_transfer', 'address', 'source_remaining', 'dest_remaining',
            'pd_count', 'pd_valid', 'pd_write', 'pd_read', 'pd_source_slot', 'pd_source_pending', 'pd_dest_pending', 'done']}


class Wrapper:
    def __init__(self, core):
        self.core = core
        self.engine = Engine()
        self.memory = Memory(core)
        self.active = self.owner = self.held_valid = self.held_owner = 0
        self.prefer_b = 1
        self.csr_address = 0xa003a000
        self.csr_words = 64
        self.csr_rsp_valid = self.csr_rsp_data = 0
        self.stored_rsp_valid = self.stored_rsp_data = 0
        self.load_kind = self.load_address = self.pack_pending = self.packed_high = 0
        self.soft_reset = self.done = 0
        self.linear_mode = 1

    def comb(self, cpu):
        core, e = self.core, self.engine
        start_ready, layer_request = core.state == 1, core.state == 2
        layer_ready = layer_request and core.parameter_count == 17408 and core.shift_count == 128
        capacity = core.capacity(self.load_kind)
        h = len(core.queue.held)
        status = self.done * 64 + int(layer_ready) * 32 + int(layer_request) * 16 + int(start_ready) * 8 + int(capacity) * 4 + int(h != 0) * 2 + int(core.state != 1)
        commands = e.commands(capacity, h == 2)
        csr = cpu['address'] in [0x40, 0x44, 0x48, 0x4c, 0x50]
        slot = not self.csr_rsp_valid or cpu['rsp_ready']
        a_valid = cpu['valid'] and not csr and slot
        b_valid = commands['pio']['valid']
        grant = self.held_owner if self.held_valid else int(bool(b_valid and (not a_valid or self.prefer_b)))
        recipient = self.owner if self.active else grant
        pio_rsp_ready = bool(e.pd_active if recipient else cpu['rsp_ready'] and not self.csr_rsp_valid)
        command = commands['pio'] if grant else cpu
        pvalid = bool(not self.active and (b_valid if grant else a_valid))
        address, reading = command['address'], command['read']
        input_wait = not reading and self.load_kind == 0 and core.state != 1 and not layer_request and not self.done and address in [0x10, 0x30] and self.load_address < (6336 if address == 0x10 else 6335) and not capacity
        pio_ready = bool((not self.stored_rsp_valid or pio_rsp_ready) and not self.pack_pending and not input_wait and
            (address != 0x24 or not reading or layer_request or h != 0 or self.done) and
            (address != 0x20 or not reading or h != 0 or self.done) and
            (address != 0x34 or not reading or h == 2 or self.done))
        fire = bool(pvalid and pio_ready)
        immediate = not self.stored_rsp_valid and fire
        data = 0
        if reading:
            if address in [4, 0x24]: data = status
            elif address == 0: data = self.done * 2 + int(core.state != 1)
            elif address == 8: data = self.load_kind
            elif address == 12: data = self.load_address
            elif address == 0x1c: data = core.item
            elif address == 0x20 and h: data = core.queue.held[0][1] & 0xffffffff
            elif address == 0x34 and h == 2: data = (core.queue.held[0][1] & 65535) | ((core.queue.held[1][1] & 65535) << 16)
            elif address == 0x28: data = 0x4b574531
            elif address == 0x2c: data = 3
        pio_data = self.stored_rsp_data if self.stored_rsp_valid else data
        pio_valid = bool(self.stored_rsp_valid or immediate)
        a_response = pio_valid and (self.active or fire) and not recipient
        b_response = pio_valid and (self.active or fire) and recipient
        csr_ready = bool(slot and (not (cpu['read'] and cpu['address'] == 0x50) or not e.pd_active))
        cpu_ready = csr_ready if csr else bool(slot and not self.active and not grant and pio_ready)
        cpu_valid = bool(self.csr_rsp_valid or a_response)
        cpu_data = self.csr_rsp_data if self.csr_rsp_valid else pio_data
        csr_fire = bool(cpu['valid'] and csr and csr_ready)
        launch = None
        if csr_fire and not cpu['read'] and cpu['address'] == 0x48 and not e.pd_active and cpu['data'] in [1, 2]:
            launch = dict(address=self.csr_address, words=self.csr_words, direction=int(cpu['data'] == 2))
        core_start = bool(fire and not reading and address == 0 and command['data'] == 1 and start_ready)
        layer_start = bool(fire and not reading and address == 0x18 and command['data'] == 1 and layer_ready)
        core_ready = capacity and not core_start and not layer_start
        limit = {0:6336, 1:17408, 5:128}.get(self.load_kind, 0)
        direct = bool(fire and not reading and address == 0x10 and core_ready and self.load_address < limit)
        packed = bool(fire and not reading and address == 0x30 and core_ready and self.load_address + 1 < limit)
        flush = bool(self.pack_pending and core_ready)
        core_in = dict(reset=self.soft_reset, start=core_start, layer_start=layer_start,
            load=direct or packed or flush, load_kind=self.load_kind, load_address=self.load_address,
            load_pair=packed and self.load_kind not in [0, 5],
            out_ready=fire and reading and address == 0x20 and h != 0,
            out_pair_ready=fire and reading and address == 0x34 and h == 2)
        memory = self.memory.comb()
        pio_return = dict(ready=bool(not self.active and grant and pio_ready), valid=bool(b_response), data=pio_data)
        snapshot = dict(cpu_cmd_ready=int(cpu_ready), cpu_rsp_valid=int(cpu_valid),
            pio_cmd_valid=int(pvalid), pio_cmd_ready=int(pio_ready), pio_rsp_valid=int(pio_valid), pio_rsp_ready=int(pio_rsp_ready),
            mem_cmd_valid=commands['memory']['valid'], mem_cmd_ready=int(memory['ready']),
            mem_rsp_valid=memory['valid'], mem_rsp_ready=int(bool(e.pd_active)),
            core_start=int(core_start), core_layer_start=int(layer_start), core_load=int(core_in['load']),
            core_load_pair=int(core_in['load_pair']))
        return dict(commands=commands, core_in=core_in, memory=memory, pio_return=pio_return,
            snapshot=snapshot, cpu_ready=cpu_ready, cpu_valid=cpu_valid, cpu_data=cpu_data,
            pvalid=pvalid, pio_ready=pio_ready, pio_valid=pio_valid, pio_data=pio_data,
            pio_rsp_ready=pio_rsp_ready, command=command, fire=fire, grant=grant,
            immediate=immediate, immediate_data=data, csr=csr, csr_fire=csr_fire,
            launch=launch, packed=packed, flush=flush, status=status)

    def tick(self, cpu, c, cycle):
        core_c = self.core.comb(c['core_in'])
        old_done = self.core.state == 0 and self.core.queue.retired == 25344
        self.engine.remember()
        self.engine.tick(c['commands'], c['memory'], c['pio_return'], c['launch'])
        self.memory.tick(c['commands']['memory'], bool(c['snapshot']['mem_rsp_ready']), cycle)
        if not self.active and c['pvalid'] and not c['pio_ready'] and not self.held_valid:
            self.held_valid, self.held_owner = 1, c['grant']
        if c['fire']:
            self.held_valid, self.owner, self.prefer_b = 0, c['grant'], 1 - c['grant']
            self.active = int(not (c['pio_valid'] and c['pio_rsp_ready']))
        elif self.active and c['pio_valid'] and c['pio_rsp_ready']:
            self.active = 0
        if self.csr_rsp_valid and cpu['rsp_ready']:
            self.csr_rsp_valid = 0
        if c['csr_fire']:
            self.csr_rsp_valid = 1
            self.csr_rsp_data = 0
            if cpu['read']:
                self.csr_rsp_data = self.csr_address if cpu['address'] == 0x40 else self.csr_words if cpu['address'] == 0x44 else (4 * 0 + 2 * self.engine.done + self.engine.pd_active)
            elif cpu['address'] == 0x40: self.csr_address = cpu['data']
            elif cpu['address'] == 0x44: self.csr_words = cpu['data']
        old_kind = self.load_kind
        if c['core_in']['load']:
            self.load_address += 2 if c['packed'] and old_kind not in [0, 5] else 1
        if c['flush']:
            self.pack_pending = 0
        if old_done:
            self.done = 1
        if self.stored_rsp_valid and c['pio_rsp_ready']:
            self.stored_rsp_valid = 0
        if c['fire']:
            self.stored_rsp_valid = 1
            self.stored_rsp_data = c['immediate_data']
            command = c['command']
            if not command['read']:
                address = command['address']
                if address == 8: self.load_kind = command['data']
                elif address == 12: self.load_address = command['data']
                elif address == 0x30 and c['packed']:
                    self.packed_high = command['data'] >> 16
                    self.pack_pending = int(old_kind in [0, 5])
        if c['immediate'] and c['pio_rsp_ready']:
            self.stored_rsp_valid = 0
        return self.core.tick(c['core_in'], core_c)

    def snapshot(self):
        return dict(load_kind=self.load_kind, load_address=self.load_address, pack_pending=self.pack_pending,
                    stored_rsp_valid=self.stored_rsp_valid, csr_rsp_valid=self.csr_rsp_valid,
                    arb_active=self.active, arb_owner=self.owner, arb_prefer_b=self.prefer_b,
                    arb_held_valid=self.held_valid, arb_held_owner=self.held_owner, **self.engine.snapshot())
