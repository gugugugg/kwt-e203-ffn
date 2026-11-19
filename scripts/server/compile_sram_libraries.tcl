set public /storage1/admin_public_dir/SRAM_Lib_2025
file mkdir build/server/technology/ram_db
foreach corner {ss_0p99v_0p99v_125c tt_1p10v_1p10v_25c} {
    foreach memory {RAMSP1024X16 RAMSP128X16} {
        set path $public/$memory/lib/${memory}_${corner}.lib
        read_lib $path
        set channel [open $path r]
        set contents [read $channel]
        close $channel
        regexp {library\s*\(\s*"?([^"\)\s]+)} $contents unused name
        write_lib $name -format db -output build/server/technology/ram_db/${memory}_${corner}.db
        remove_lib $name
    }
}
puts "XPIAN_SRAM_DB_READY"
exit
