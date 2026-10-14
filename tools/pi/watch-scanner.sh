#!/bin/sh
# Log every appearance and disappearance of the scanner on USB and dump its
# descriptors once per appearance. If probe_readonly.py and its venv are
# installed under ~/plustek-preservation, also run the read-only probe on
# each appearance, followed by status polling every 20 s until the scanner
# leaves the bus (which also shows whether host traffic delays standby).
# The file ~/plustek-preservation/probe-disabled turns the probe off, so
# that another tool (flash_dump.py) can have the scanner to itself.
# Before the probe, keep_awake.py drives the standby line high on each
# appearance, but only while ~/plustek-preservation/keep-awake-enabled
# exists (its docstring says on which board revision that is safe).
#
# Usage: watch-scanner.sh [vendor:product] [log directory]
vendor_product="${1:-05e3:0103}"
log_directory="${2:-$HOME/scanner-log}"
project_directory="$HOME/plustek-preservation"
probe_script="$project_directory/probe_readonly.py"
venv_python="$project_directory/venv/bin/python"
probe_disabled="$project_directory/probe-disabled"
keep_awake_script="$project_directory/keep_awake.py"
keep_awake_enabled="$project_directory/keep-awake-enabled"
mkdir -p "$log_directory"
present=0
while true; do
    if lsusb -d "$vendor_product" >/dev/null 2>&1; then
        if [ "$present" = 0 ]; then
            stamp=$(date -u +%Y%m%dT%H%M%SZ)
            echo "$stamp connected" >> "$log_directory/events.log"
            sudo lsusb -v -d "$vendor_product" > "$log_directory/descriptors-$stamp.txt" 2>&1
            if [ -f "$keep_awake_enabled" ] && [ -f "$keep_awake_script" ] \
                && [ -f "$project_directory/flash_dump.py" ] && [ -x "$venv_python" ]; then
                sudo -n "$venv_python" "$keep_awake_script" "$log_directory/keep-awake-$stamp.jsonl" \
                    > /dev/null 2>> "$log_directory/events.log"
                echo "$stamp keep awake exit $?" >> "$log_directory/events.log"
            fi
            if [ -f "$probe_disabled" ]; then
                echo "$stamp probe disabled" >> "$log_directory/events.log"
            elif [ -f "$probe_script" ] && [ -x "$venv_python" ]; then
                sudo "$venv_python" "$probe_script" --watch 20 > "$log_directory/probe-$stamp.jsonl" 2>&1 &
            fi
            present=1
        fi
    elif [ "$present" = 1 ]; then
        echo "$(date -u +%Y%m%dT%H%M%SZ) disconnected" >> "$log_directory/events.log"
        present=0
    fi
    sleep 1
done
