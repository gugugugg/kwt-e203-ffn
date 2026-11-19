"""Compare the four authorized schedules against the native 3K baseline."""

from collections import deque
from concurrent.futures import ProcessPoolExecutor
import json
import importlib.util
from pathlib import Path

from lossless import Decoder, pack_input, pack_tile

spec = importlib.util.spec_from_file_location('sysbus32_baseline', Path(__file__).with_name('model.py'))
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
REPORT, SingleBusTask, base = baseline.REPORT, baseline.SingleBusTask, baseline.base


OUT = REPORT.parent / 'ffn_sysbus32_lossless'
LIMIT = 545454


class Task(SingleBusTask):
    def __init__(self, case, controls, cpu, kickoff, mode):
        super().__init__(case, controls, cpu, kickoff)
        self.host_first = mode in ('H', 'CH')
        self.encoded = mode in ('C', 'CH')
        if not self.encoded:
            return
        values = [v for i in range(base.INPUT_WORDS) for v in base.halves(self.source[i])]
        packed, split = pack_input(values, self.identities)
        self.decoders = {-1: Decoder(True, self.identities)}
        self.wire_payload = dict(enumerate(packed))
        self.tile_by_word = {i: -1 for i in range(len(packed))}
        packet_addresses = []
        address = base.PARAMETER_BASE
        for tile in range(base.TILES):
            start = base.PARAMETER_BASE + tile * base.PACKET_WORDS
            raw = [self.source[i] for i in range(start, start + base.PACKET_WORDS)]
            words = pack_tile(raw)
            addresses = list(range(address, address + len(words)))
            self.wire_payload.update(zip(addresses, words))
            self.tile_by_word.update((i, tile) for i in addresses)
            packet_addresses.append(addresses)
            address += len(words)
        self.order = packet_addresses[0] + list(range(split)) + packet_addresses[1] + \
            list(range(split, len(packed))) + [i for packet in packet_addresses[2:] for i in packet]
        self.host_order = [(0, packed[0])] + list(controls) + [(i, self.wire_payload[i]) for i in self.order if i]
        self.wire_return = deque()
        self.decoded = {-1: 0}
        self.wire_tail = None
        self.wire_started = set()

    def next_source(self):
        if not self.encoded:
            return super().next_source()
        if self.cycle < self.kickoff or self.read_index == len(self.order):
            return None
        if len(self.wire_return) + self.source_in_flight >= 2:
            return None
        address = self.order[self.read_index]
        if address not in self.shared:
            self.stats['dma_wait_host_word'] += 1
            return None
        tile = self.tile_by_word[address]
        if tile >= 0 and ((self.pages[tile % 2] and self.pages[tile % 2].tile != tile) or tile > self.oldest+1):
            self.stats['dma_wait_page_release'] += 1
            return None
        return address

    def queue_request(self):
        source = self.next_source() if self.encoded or len(self.incoming) + self.source_in_flight < 2 else None
        occupancy = len(self.slots[0])
        if occupancy >= 24:
            self.preempt = True
        elif occupancy <= 16:
            self.preempt = False
        if self.cpu_commands and self.cpu_commands[0]['accept'] <= self.cycle:
            cmd = self.cpu_commands[0]
            address = (cmd['address'] - base.baseline.t.BASE) // 4
            if not cmd['read'] or address in self.shared:
                self.cpu_commands.popleft()
                self.commands.append(('cpu_read' if cmd['read'] else 'cpu_write', address, cmd['data']))
                return
        host = self.host_index < len(self.host_order)
        if self.out_held and (self.preempt or (source is None and not (self.host_first and host))):
            self.commands.append(('result', None, self.out_held.popleft()))
        elif source is not None:
            self.commands.append(('source', source, None))
            self.source_in_flight += 1
            self.read_index += 1
            if self.encoded:
                tile = self.tile_by_word[source]
                if tile >= 0 and tile not in self.wire_started:
                    assert self.pages[tile % 2] is None
                    self.wire_started.add(tile)
                    self.pages[tile % 2] = base.Page(tile)
                    self.decoders[tile] = Decoder(False)
                    self.decoded[tile] = 0
            elif source >= base.PARAMETER_BASE:
                tile, offset = divmod(source - base.PARAMETER_BASE, base.PACKET_WORDS)
                if offset == 0:
                    assert self.pages[tile % 2] is None
                    self.pages[tile % 2] = base.Page(tile)
        elif host:
            address, data = self.host_order[self.host_index]
            self.commands.append(('host', address, data))
            self.host_index += 1

    def commit_request(self, kind, address, data):
        if not self.encoded or kind != 'host':
            return super().commit_request(kind, address, data)
        assert address not in self.out_memory
        self.shared[address] = data
        self.stats['bus_host'] += 1
        self.stats['host_payload_commits' if address in self.wire_payload else 'host_setup_commits'] += 1
        self.responses.append((kind, address, data))

    def transfer(self, ports):
        if not self.encoded:
            return super().transfer(ports)
        # The base ICB transfer operates on the raw returned-word queue. The
        # decoder receives only returned words and loads through the old port.
        decoded, self.incoming = self.incoming, self.wire_return
        super().transfer(ports)
        self.incoming = decoded

    def decode(self):
        if self.wire_return:
            address, word = self.wire_return[0]
            tile = self.tile_by_word[address]
            current = self.decoders[tile]
            if current.bits <= 32:
                self.wire_return.popleft()
                current.feed(word)
        # Only the oldest parameter page decoder and the input decoder can
        # have partially consumed packets. Drain at most one decoded word.
        for tile, decoder in self.decoders.items():
            if decoder.output and len(self.incoming) < 2 and self.wire_tail is None:
                start = 0 if tile == -1 else base.PARAMETER_BASE + base.PACKET_WORDS * tile
                index = start + self.decoded[tile]
                value = decoder.output.popleft()
                assert self.source[index] == value, (self.case, tile, index, self.source[index], value)
                self.wire_tail = (index, value)
                self.decoded[tile] += 1
            decoder.step()
        if self.wire_tail:
            self.incoming.append(self.wire_tail)
            self.wire_tail = None

    def run(self):
        if not self.encoded:
            return super().run()
        while 'final_ack' not in self.marks and self.cycle < 110000:
            self.tokens[self.cycle % 64] = None
            ports = set()
            self.finish_output_column(ports)
            self.retire_pages()
            self.issue(ports)
            self.load_private(ports, self.mac())
            self.decode()
            self.transfer(ports)
            self.cycle += 1
        passed = 'final_ack' in self.marks
        if passed:
            assert self.read_index == len(self.order) == self.stats['host_payload_commits']
            assert self.stats['read_ack'] == self.read_index and self.stats['host_setup_commits'] == 10
            assert self.stats['write_ack'] == self.output_written == base.RESULT_COUNT // 2
            assert self.decoded[-1] == base.INPUT_WORDS and all(self.decoded[t] == 532 for t in range(16))
            assert self.mac_operations == base.RESULT_COUNT*64 and self.stats['quant_halfwords'] == base.RESULT_COUNT
            assert not self.slots[0] and self.oldest == 16
            for index in range(0, base.RESULT_COUNT, 2):
                assert base.halves(self.out_memory[base.RESULT_BASE + index//2]) == tuple(self.golden[index:index+2])
        row = self.summary(passed)
        row['encoded_words'] = len(self.order)
        row['decode_refill_waits'] = sum(d.stalls for d in self.decoders.values())
        return row


def simulate(case, mode, controls, cpu, kickoff):
    return Task(case, controls, cpu, kickoff, mode).run()


def main():
    _, controls, _, _ = base.baseline.observe()
    controls += [(base.baseline.t.READY_WORD, 1)]
    calibration = json.loads((REPORT / 'baseline-calibration.json').read_text())
    cpu = calibration['cpu_requests']
    for cmd in cpu:
        if not cmd['read']:
            cmd['data'] = 1
    kickoff = calibration['first_native_dma_accept']
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for mode in ('M0', 'H', 'C', 'CH'):
            jobs = [pool.submit(simulate, case, mode, controls, cpu, kickoff) for case in range(12)]
            rows = [job.result() for job in jobs]
            total = sum(r['cold_cycles'] for r in rows) if all(r['complete'] for r in rows) else None
            results[mode] = dict(cycles=total, throughput=1800000000 / total if total else None, rows=rows)
            print(mode, total, results[mode]['throughput'], flush=True)
    assert results['M0']['cycles'] == 583344
    feasible = [mode for mode in ('H', 'C', 'CH') if results[mode]['cycles'] and results[mode]['cycles'] <= LIMIT]
    selected = min(feasible, key=lambda mode: results[mode]['cycles']) if feasible else None
    (OUT/'model-selection.json').write_text(json.dumps(dict(selected=selected, cycle_limit=LIMIT, results=results), indent=2)+'\n')
    print('selected', selected, flush=True)


if __name__ == '__main__':
    main()
