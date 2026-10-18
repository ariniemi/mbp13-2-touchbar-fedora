#!/bin/sh
# Load the T1 Touch Bar modules and move the second iBridge HID interface
# from hid-sensor-hub to apple-ibridge-hid (hid-sensor-hub grabs it first).
modprobe apple-ibridge || exit 1
modprobe apple-ib-tb || exit 1
sleep 2
for d in /sys/bus/hid/devices/0003:05AC:8600.*; do
  [ -e "$d/driver" ] || continue
  if [ "$(basename "$(readlink "$d/driver")")" = "hid-sensor-hub" ]; then
    n=$(basename "$d")
    echo "$n" > /sys/bus/hid/drivers/hid-sensor-hub/unbind
    echo "$n" > /sys/bus/hid/drivers/apple-ibridge-hid/bind
  fi
done
