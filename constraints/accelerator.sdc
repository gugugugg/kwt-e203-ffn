# Initial 150 MHz clock constraint. Update I/O constraints after platform integration.
# This file is a starting constraint, not evidence of timing closure.
create_clock -name clk -period 6.666666 [get_ports clk]
