set root build/server/official_2025/e203_hbirdv2-master/rtl/e203/mem_gen
file mkdir build/server/technology/platform_ram_db
set libraries [exec find $root -iname *_ss_0p99v_0p99v_125c.lib]
lappend libraries /storage1/admin_public_dir/SRAM_Lib_2025/RAMSP4096X16/lib/RAMSP4096X16_ss_0p99v_0p99v_125c.lib
foreach path $libraries {
    read_lib $path
    set stream [open $path r]
    set text [read $stream]
    close $stream
    regexp {library\s*\(\s*"?([^"\)\s]+)} $text unused name
    write_lib $name -format db -output build/server/technology/platform_ram_db/[file rootname [file tail $path]].db
    remove_lib $name
}
puts "XPIAN_PLATFORM_RAM_DB_READY"
exit
