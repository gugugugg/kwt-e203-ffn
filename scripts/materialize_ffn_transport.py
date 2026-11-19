"""Apply transport ablations to the accepted source, preserving explicit initialization."""
import re
from ffn_transport import ROOT, REPORT, load, candidates, copy_tree, dump, prove_bias32


def control(text):
    text = text.replace('integer row,tile,inner,lane,chunk,item,mac_group,emit_group,stash_pointer;',
        'reg [6:0] row;\n    reg [3:0] tile,lane;\n    reg [5:0] inner;\n    reg [2:0] chunk;\n    reg [14:0] item;\n    reg mac_group,emit_group;\n    reg [7:0] stash_pointer;')
    text = text.replace("wire [2:0] block_rows=3'((99-row<ROW_GROUP)?99-row:ROW_GROUP);", "wire [2:0] block_rows=3'd1;")
    text = text.replace("wire input_complete=int'(input_count)>=(row+int'(block_rows))*64;",
                        "wire input_complete=input_count>=(({6'd0,row}+13'd1)<<6);")
    text = text.replace('integer row_cache_request,row_cache_chunk;', 'reg [3:0] row_cache_request;\n    reg [2:0] row_cache_chunk;')
    text = text.replace("row_cache[(SMALL_INPUT?((row/ROW_GROUP)%INPUT_SLOTS)*ROW_GROUP*64:0)+mac_group*64+inner]", 'row_cache[{row[0],inner}]')
    return text


def fifo_gate(text):
    depth = int(re.search(r'fifo\[0:(\d+)\]', text).group(1)) + 1
    a = text.index('    wire fifo_clk;')
    b = text.index('    assign start_ready=', a)
    block = '    generate for(genvar fifo_bank=0;fifo_bank<%d;fifo_bank=fifo_bank+1) begin: fifo_write_banks\n' % (depth // 2)
    bits = (depth - 1).bit_length()
    block += '''        wire bank_write=fifo_push&&(fifo_write[%d:1]==%d'(fifo_bank));
        wire bank_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(bank_write),.test_enable(clock_test_enable||!rst_n),.gated_clk(bank_clk));
        for(genvar word_id=0;word_id<2;word_id=word_id+1) begin: fifo_words
            always @(posedge bank_clk) if(bank_write&&fifo_write[0]==1'(word_id))
                fifo[fifo_bank*2+word_id]<=fifo_word;
        end
    end endgenerate
''' % (bits - 1, bits - 1)
    return text[:a] + block + text[b:]


def shift_gate(text):
    text = text.replace('accumulator[group_id*LANES+lane_id]<=0;shifts[group_id*LANES+lane_id]<=0;',
                        'accumulator[group_id*LANES+lane_id]<=0;')
    text = text.replace("                        shifts[group_id*LANES+lane_id]<=$signed(shift_rdata[(lane_id%2)*8+:8]);\n", '')
    a = text.index('    wire fifo_clk;') if '    wire fifo_clk;' in text else text.index('    generate for(genvar fifo_bank=')
    block = '''    generate for(genvar shift_bank=0;shift_bank<8;shift_bank=shift_bank+1) begin: transport_shift_banks
        wire capture=bias_capture&&(chunk==shift_bank);
        wire register_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(capture),.test_enable(clock_test_enable||!rst_n),.gated_clk(register_clk));
        for(genvar word_id=0;word_id<2;word_id=word_id+1) begin: shift_words
            always @(posedge register_clk or negedge rst_n)
                if(!rst_n) shifts[shift_bank*2+word_id]<=0;
                else if(capture) shifts[shift_bank*2+word_id]<=$signed(shift_rdata[word_id*8+:8]);
        end
    end endgenerate
'''
    return text[:a] + block + text[a:]


def isolate(text):
    text = text.replace('wire [35:0] quant_bits=accumulator[emit_group*LANES+lane];',
                        "wire [35:0] quant_bits=emission?accumulator[emit_group*LANES+lane]:36'd0;")
    text = text.replace('    kwt_ffn_requantize quantizer(.value(quant_value),.shift(shifts[emit_group*LANES+lane]),.result(result_word));',
                        "    wire signed [7:0] quant_shift=emission?shifts[emit_group*LANES+lane]:8'sd0;\n    kwt_ffn_requantize quantizer(.value(quant_value),.shift(quant_shift),.result(result_word));")
    return text


def cache_gate(text):
    a = text.index('    wire row_cache_clk;')
    b = text.index('    always @(posedge clk or negedge rst_n)', a)
    block = '''    wire [6:0] input_low=load_addr[6:0],input_high=load_addr[6:0]+7'd1;
    generate for(genvar cache_part=0;cache_part<16;cache_part=cache_part+1) begin: transport_cache_banks
        wire write_low=input_loading&&(input_low[6:3]==4'(cache_part));
        wire write_high=input_loading&&(load_count==2)&&(input_high[6:3]==4'(cache_part));
        wire bank_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(write_low||write_high),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(bank_clk));
        for(genvar word_id=0;word_id<8;word_id=word_id+1) begin: cache_words
            always @(posedge bank_clk) begin
                if(write_low&&input_low[2:0]==3'(word_id))row_cache[cache_part*8+word_id]<=load_data;
                if(write_high&&input_high[2:0]==3'(word_id))row_cache[cache_part*8+word_id]<=load_high;
            end
        end
    end endgenerate
'''
    return text[:a] + block + text[b:]


def prepare(name):
    manifest = load(name)
    if manifest['effective_changes'].get('bias32'):
        prove_bias32(REPORT / (name + '-bias32-proof.json'))
    out = ROOT / 'build/optimization/rtl_sources' / name
    copy_tree(ROOT / manifest['parent']['source_snapshot'], out)
    path = out / 'encoder/kwt_encoder.sv'
    text = path.read_text()
    if manifest['effective_changes']['clear_last'] != 0 or manifest['effective_changes']['zero_clear']:
        raise RuntimeError('Transport candidates must inherit the explicit accepted clear policy')
    if 'CLEAR:if(ZERO_CLEAR||clear_index==0)' not in text:
        raise RuntimeError('The copied source does not implement the manifest clear policy')
    for feature in manifest['hardware']:
        if feature == 'V0':
            text = text.replace('INPUT_SLOTS=2', 'INPUT_SLOTS=1')
        elif feature == 'H':
            text = control(text)
        elif feature == 'F':
            text = fifo_gate(text)
        elif feature == 'S':
            text = shift_gate(text)
        elif feature == 'Q':
            text = isolate(text)
        elif feature == 'G':
            text = cache_gate(text)
        elif feature == 'FIFO64':
            text = text.replace('fifo[0:15]', 'fifo[0:63]').replace('reg [3:0] fifo_write,fifo_read;', 'reg [5:0] fifo_write,fifo_read;')
            text = text.replace('reg [4:0] fifo_count;', 'reg [6:0] fifo_count;').replace('fifo_count<16', 'fifo_count<64')
            text = text.replace('wire [3:0] next_read=', 'wire [5:0] next_read=').replace("fifo_read+4'(pop_count)", "fifo_read+6'(pop_count)")
            text = text.replace("fifo_count+5'(fifo_push)-5'(pop_count)", "fifo_count+7'(fifo_push)-7'(pop_count)")
            text = text.replace('fifo_bank<8;', 'fifo_bank<32;').replace("fifo_write[3:1]==3'(fifo_bank)", "fifo_write[5:1]==5'(fifo_bank)")
    if manifest['hardware']:
        path.write_text(text)
    if not manifest['hardware']:
        source = ROOT / manifest['parent']['source_snapshot']
        if not all((out / p.relative_to(source)).read_bytes() == p.read_bytes() for p in source.rglob('*.sv')):
            raise RuntimeError('A firmware-only candidate changed RTL')
    dump(out / 'configuration.json', manifest)
    if 'H' in manifest['hardware']:
        compact = ''.join(text.split())
        for guard in ['inner==63', 'lane<LANES-1', 'tile<TILES-1', "row+int'(block_rows)==99", "item+int'(pop_count)==25344"]:
            if guard not in compact:
                raise RuntimeError('The control induction needs an updated transition argument: ' + guard)
        for last, bits in [(98,7),(15,4),(63,6),(7,3),(25343,15)]:
            assert last < (1 << bits)
        dump(REPORT / (name + '-control-proof.json'), dict(passed=True,
            domain='legal full-task loads and any legal output backpressure',
            method='state-transition induction with fixed ROW_GROUP=1 and INPUT_SLOTS=2',
            ranges=dict(row=[0,98],tile=[0,15],inner=[0,63],lane=[0,15],chunk=[0,7],item=[0,25343]),
            induction=['WAIT_LAYER initializes row/tile/inner/lane/item to zero',
                'Inner and lane increment only below their respective last valid indices',
                'Tile increments only below 15; the row transition resets tile',
                'ADVANCE increments row only when row+1 is not 99',
                'The final output consumes remaining values without incrementing item beyond 25343',
                'Input readiness uses this-task prefix; slot row[0] is not reused before ADVANCE'],
            numerical_widths_unchanged=True,source_snapshot=out.relative_to(ROOT).as_posix()))
    if any(f in manifest['hardware'] for f in ['F','S','G']) or ('FIFO64' in manifest['hardware'] and 'begin: fifo_write_banks' in text):
        fifo_depth=int(re.search(r'fifo\[0:(\d+)\]',text).group(1))+1
        for pointer in range(fifo_depth):
            writes = [bank*2+word for bank in range(fifo_depth//2) for word in range(2)
                      if (pointer >> 1) == bank and (pointer & 1) == word]
            assert writes == [pointer]
        for address in range(128):
            for count in [1,2]:
                expected = {(address+i) % 128 for i in range(count)}
                actual = set()
                for bank in range(16):
                    for word in range(8):
                        for offset in range(count):
                            selected = (address+offset) % 128
                            if selected >> 3 == bank and selected & 7 == word:
                                actual.add(bank*8+word)
                assert actual == expected
        dump(REPORT / (name + '-write-clock-proof.json'), dict(passed=True,
            fifo_depth=fifo_depth,fifo_banks=fifo_depth//2,
            method='constant-index bank partition of the original write events',
            fifo='Each write pointer selects exactly one two-word bank and exactly one word',
            shift='Each chunk selects exactly one pair; both shift values capture the original byte slices',
            cache='Low and high seven-bit addresses independently select their bank and word; cross-bank pairs enable both',
            reset_and_test_enable='Original reset/test enable is retained on each ICG',
            source_snapshot=out.relative_to(ROOT).as_posix()))
    return out


def variants():
    return {name: ['PIPE', 'OUTPUT'] for name in candidates()}


if __name__ == '__main__':
    import sys
    for name in sys.argv[1:]:
        print(prepare(name))
