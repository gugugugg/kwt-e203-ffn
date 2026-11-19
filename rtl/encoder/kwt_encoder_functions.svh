// Include inside a module; also accepted by the native Yosys SV frontend.
function automatic signed [63:0] rne(input signed [63:0] v, input integer s);
    reg signed [63:0] q,r,h;
    begin
        if(s<=0) rne=v<<<(-s);
        else if(s<=62) begin
            q=v>>>s; r=v-(q<<<s); h=64'sd1<<<(s-1);
            rne=q+64'((r>h)||((r==h)&&q[0]));
        end else rne=0;
    end
endfunction
function automatic [15:0] sat(input signed [63:0] v);
    if(v>32767) sat=16'h7fff;
    else if(v< -32768) sat=16'h8000;
    else sat=v[15:0];
endfunction
function automatic signed [63:0] sx16(input [15:0] v);
    sx16={{48{v[15]}},v};
endfunction
