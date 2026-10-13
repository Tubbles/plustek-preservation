#!/bin/sh
# Log every appearance and disappearance of the scanner on USB and dump its
# descriptors once per appearance. Only reads descriptors, sends nothing to
# the device.
#
# Usage: watch-scanner.sh [vendor:product] [log directory]
vendor_product="${1:-05e3:0103}"
log_directory="${2:-$HOME/scanner-log}"
mkdir -p "$log_directory"
present=0
while true; do
    if lsusb -d "$vendor_product" >/dev/null 2>&1; then
        if [ "$present" = 0 ]; then
            stamp=$(date -u +%Y%m%dT%H%M%SZ)
            echo "$stamp connected" >> "$log_directory/events.log"
            sudo lsusb -v -d "$vendor_product" > "$log_directory/descriptors-$stamp.txt" 2>&1
            present=1
        fi
    elif [ "$present" = 1 ]; then
        echo "$(date -u +%Y%m%dT%H%M%SZ) disconnected" >> "$log_directory/events.log"
        present=0
    fi
    sleep 1
done
