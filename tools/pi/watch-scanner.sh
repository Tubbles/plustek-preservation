#!/bin/sh
# Log every appearance and disappearance of the scanner on USB and dump its
# descriptors once per appearance. If probe_readonly.py and its venv are
# installed under ~/plustek-preservation, also run the read-only probe on
# each appearance, followed by status polling every 20 s until the scanner
# leaves the bus (which also shows whether host traffic delays standby).
# The file ~/plustek-preservation/probe-disabled turns the probe off, so
# that another tool (flash_dump.py) can have the scanner to itself.
#
# Usage: watch-scanner.sh [vendor:product] [log directory]
vendor_product="${1:-05e3:0103}"
log_directory="${2:-$HOME/scanner-log}"
project_directory="$HOME/plustek-preservation"
probe_script="$project_directory/probe_readonly.py"
probe_python="$project_directory/venv/bin/python"
probe_disabled="$project_directory/probe-disabled"
mkdir -p "$log_directory"
present=0
while true; do
    if lsusb -d "$vendor_product" >/dev/null 2>&1; then
        if [ "$present" = 0 ]; then
            stamp=$(date -u +%Y%m%dT%H%M%SZ)
            echo "$stamp connected" >> "$log_directory/events.log"
            sudo lsusb -v -d "$vendor_product" > "$log_directory/descriptors-$stamp.txt" 2>&1
            if [ -f "$probe_disabled" ]; then
                echo "$stamp probe disabled" >> "$log_directory/events.log"
            elif [ -f "$probe_script" ] && [ -x "$probe_python" ]; then
                sudo "$probe_python" "$probe_script" --watch 20 > "$log_directory/probe-$stamp.jsonl" 2>&1 &
            fi
            present=1
        fi
    elif [ "$present" = 1 ]; then
        echo "$(date -u +%Y%m%dT%H%M%SZ) disconnected" >> "$log_directory/events.log"
        present=0
    fi
    sleep 1
done
