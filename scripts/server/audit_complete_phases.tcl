set source_svf [file normalize build/server/complete_soc_sm40_complete_v2_ss_ema2/design.svf]
file mkdir reports/complete_soc/phase_audit
cd reports/complete_soc/phase_audit
set_svf $source_svf
exit
