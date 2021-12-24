
# Design
set ::env(DESIGN_NAME) "aes128"

set ::env(VERILOG_FILES) "$::env(DESIGN_DIR)/src/aes128.v"

set ::env(CLOCK_PORT) "clk"
set ::env(CLOCK_NET) $::env(CLOCK_PORT)

set ::env(GLB_RESIZER_HOLD_MAX_BUFFER_PERCENT) {60}

set filename $::env(DESIGN_DIR)/$::env(PDK)_$::env(STD_CELL_LIBRARY)_config.tcl
if { [file exists $filename] == 1} {
	source $filename
}
