"""Apply the round-six weight-address bijection to the frozen FFN core."""


def _replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Inspect the frozen Gray edit point: ' + before[:100])
    return text.replace(before, after, 1)


def transform_core(text):
    text = _replace_once(
        text,
        "    wire [15:0] weight_address=16'(int'(request_inner)*256+tile*LANES);",
        '''    function automatic [5:0] ap_gray6(input [5:0] value);
        begin ap_gray6=value^(value>>1);end
    endfunction
    wire [12:0] ap_weight_read_address={3'b000,ap_gray6(request_inner),4'(tile)};''')
    text = _replace_once(
        text,
        "        begin ld_parameter_address=13'((int'(packed_address)%64)*TILES+int'(packed_address)/64);end",
        "        begin ld_parameter_address={3'b000,ap_gray6(packed_address[5:0]),packed_address[9:6]};end")
    return _replace_once(
        text,
        "pm_addr[b*13+:13]=13'(int'(weight_address)/LANES);",
        'pm_addr[b*13+:13]=ap_weight_read_address;')
