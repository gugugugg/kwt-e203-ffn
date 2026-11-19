set activity_audit [exec python3 scripts/server/audit_optimization_activity.py $env(XPIAN_TAG)]
puts $activity_audit
puts "XPIAN_SHARED_VALID_CELL_FUNCTION=[get_attribute [get_lib_pins */NOR2BV0_12TR40/ZN] function]"
if {[string first XPIAN_ACTIVITY_SAME_AS_VERIFIED=1 $activity_audit] >= 0} {
    source scripts/server/complete_activity_polarity.tcl
    puts "XPIAN_ACTIVITY_VERIFIED_CORRECTION_APPLIED=1"
} else {
    puts "XPIAN_ACTIVITY_POLARITY_REQUIRES_REVIEW=1"
}
