"""Four-bank feasibility for the fixed M2 event schedule, at 16-int16 granularity."""
from collections import Counter, defaultdict, deque
import gzip
import json
from model import REPORT


def input_key(row, k):
    return 'I:%d:%d' % (row, k // 16)


def output_key(index):
    row, col = divmod(index, 256)
    return 'O:%d:%d:%d' % (row, col // 32, col & 1)


def study(name='M2', output_prefix=''):
    blocks = {}
    graph = defaultdict(set)
    fifo = deque()
    output_reads = Counter()
    written = Counter()
    access_histogram = Counter()
    peak_access = []
    def touch(key, cycle, access):
        if key not in blocks:
            if access != 'write':
                raise RuntimeError('Reading a block before its first write: ' + key)
            blocks[key] = dict(key=key, first_write=cycle, last_access=cycle,
                               release=None, writes=0, accesses=0)
        b = blocks[key]
        b['last_access'] = cycle
        b['accesses'] += 1
        if access == 'write':
            b['writes'] += 1
            written[key] += 1

    with gzip.open(REPORT / (name + '-events.jsonl.gz'), 'rt', encoding='utf-8') as stream:
        for line in stream:
            e = json.loads(line)
            cycle = e['cycle']
            accesses = []
            if e['input_write'] is not None:
                row, k = divmod(e['input_write'], 64)
                key = input_key(row, k)
                touch(key, cycle, 'write')
                accesses.append((key, 'input_write'))
            if e['input_read'] is not None:
                k = e['input_read']
                for row in [e['row']] + ([e['row'] + 1] if e['row'] < 98 else []):
                    key = input_key(row, k)
                    touch(key, cycle, 'read')
                    accesses.append((key, 'input_read'))
                    if e['tile'] == 31 and k % 16 == 15:
                        blocks[key]['release'] = cycle + 1
            if e['drain0']:
                if not fifo:
                    raise RuntimeError('Missing row0 FIFO token')
                index = fifo.popleft()
                key = output_key(index)
                touch(key, cycle, 'write')
                accesses.append((key, 'row0_write'))
            if e['quant']:
                q = e['quant']
                pair = [q['row'] * 256 + q['column'] + i for i in range(2)]
                if q['row'] & 1:
                    for index in pair:
                        key = output_key(index)
                        touch(key, cycle, 'write')
                        accesses.append((key, 'row1_write'))
                else:
                    fifo.extend(pair)
            if e['read0'] or e['read1']:
                index = e['item'] + e['held'] + e['pending']
                for offset in range(e['issue']):
                    key = output_key(index + offset)
                    touch(key, cycle, 'read')
                    accesses.append((key, 'output_read'))
                    output_reads[key] += 1
                    if output_reads[key] == 16:
                        if written[key] != 16:
                            raise RuntimeError('Output block released before all sixteen writes')
                        blocks[key]['release'] = cycle + 1
            if accesses:
                access_histogram[len(accesses)] += 1
                if len(accesses) >= 5 and len(peak_access) < 12:
                    peak_access.append(dict(cycle=cycle, row=e['row'], tile=e['tile'], accesses=accesses))
                for index, (key, unused) in enumerate(accesses):
                    for other, unused2 in accesses[index + 1:]:
                        if other == key:
                            raise RuntimeError('Same logical block requires two physical operations in one cycle')
                        graph[key].add(other)
                        graph[other].add(key)
    if fifo or any(b['release'] is None or b['writes'] != 16 for b in blocks.values()):
        raise RuntimeError('Incomplete input/output lifetime accounting')
    allocated = {}
    occupied = [[None] * 8 for unused in range(4)]
    failed = None
    for b in sorted(blocks.values(), key=lambda x: (x['first_write'], x['key'])):
        cycle, key = b['first_write'], b['key']
        for bank in range(4):
            for slot in range(8):
                old = occupied[bank][slot]
                if old is not None and blocks[old]['release'] <= cycle:
                    occupied[bank][slot] = None
        forbidden = {allocated[other][0] for other in graph[key] if other in allocated}
        choice = next(((bank, slot) for bank in range(4) for slot in range(8)
                       if bank not in forbidden and occupied[bank][slot] is None), None)
        if choice is None:
            failed = dict(key=key, cycle=cycle, lifetime=b, forbidden_banks=sorted(forbidden),
                          occupied=occupied, assigned_blocks_before_failure=len(allocated))
            break
        bank, slot = choice
        occupied[bank][slot] = key
        allocated[key] = choice
    changes = []
    for b in blocks.values():
        changes.extend([(b['first_write'], 1), (b['release'], -1)])
    live = peak = 0
    for cycle, delta in sorted(changes, key=lambda x: (x[0], x[1])):
        live += delta
        peak = max(peak, live)
    result = dict(model='M3', source_schedule=name, allocation_unit_int16=16,
                  macro_count=4, depth_per_macro=128, single_physical_port_per_macro=True,
                  logical_blocks=len(blocks), all_lifetimes_accounted=True,
                  peak_live_blocks=peak, physical_block_capacity=32,
                  simultaneous_access_histogram=dict(sorted(access_histogram.items())),
                  five_access_examples=peak_access, fixed_schedule_bank_lower_bound=max(access_histogram),
                  allocation_passed=failed is None, first_fit_failure=failed,
                  status='negative_for_fixed_first_fit_allocation' if failed else 'allocation_model_feasible',
                  interpretation='The specified first-fit mapping failed. This does not reject other allocations even for the same schedule. More than four simultaneous physical operations, if observed, would separately reject the unretimed schedule at four banks.',
                  cycles_with_added_port_stalls=None, native_throughput=None, area=None, power=None)
    (REPORT / (output_prefix+'M3-result.json')).write_text(json.dumps(result, indent=2))
    (REPORT / (output_prefix+'lifetimes.json')).write_text(json.dumps(sorted(blocks.values(), key=lambda b: b['first_write']), indent=2))
    (REPORT / (output_prefix+'M3-allocation.json')).write_text(json.dumps(allocated, indent=2))
    return result


if __name__ == '__main__':
    print(json.dumps(study(), indent=2))
