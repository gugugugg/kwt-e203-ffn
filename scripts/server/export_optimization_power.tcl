# Hierarchical report formatting stays at three digits in this PT version.
# Preserve that native report, and export full design attributes in watts.
file copy -force $report/power.rpt $report/power_hierarchy.rpt
redirect $report/power_total.rpt {report_power -verbose -significant_digits 6}
set fields {}
foreach name {internal_power switching_power leakage_power total_power} {
    lappend fields [get_attribute [current_design] $name]
}
set stream [open $report/power_values.json w]
puts $stream [format {{"source":"native PrimeTime current_design attributes","unit":"W","internal_w":%.17g,"switching_w":%.17g,"leakage_w":%.17g,"total_w":%.17g}} {*}$fields]
close $stream
set stream [open $report/power.rpt w]
puts $stream "# Native design-attribute export; unit W. Original reports: power_hierarchy.rpt, power_total.rpt."
puts $stream [format {kwt_complete_soc %.17e %.17e %.17e %.17e} {*}$fields]
close $stream
puts "XPIAN_POWER_PRECISE_EXPORT=1"
