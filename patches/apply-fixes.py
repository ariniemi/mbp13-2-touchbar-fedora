#!/usr/bin/env python3
"""Apply the two source fixes to F13-Kr1pt0n/macbook-pro-touchbar-driver
(tested on commit as of Oct 2026, kernel 7.2.11, Fedora 44).

Usage: python3 apply-fixes.py /path/to/driver/source
Idempotent. Keeps .orig backups on first run.
"""
import re, shutil, sys, os

d = sys.argv[1] if len(sys.argv) > 1 else '.'

def backup(p):
    if not os.path.exists(p + '.orig'):
        shutil.copy(p, p + '.orig')

# Fix 1: struct tb_touch is embedded by value before it is defined
# ("field 'touch' has incomplete type"). Move the definition up.
p = os.path.join(d, 'apple-ib-tb.c')
s = open(p).read()
m = re.search(r'struct tb_touch \{\n.*?\n\};\n', s, re.S)
first_use = s.find('struct tb_touch       touch;')
if m and first_use != -1 and m.start() > first_use:
    backup(p)
    blk = m.group(0)
    s = s.replace(blk, '', 1)
    idx = [x.end() for x in re.finditer(r'^#include .*\n', s, re.M)][-1]
    s = s[:idx] + '\n' + blk + s[idx:]
    open(p, 'w').write(s)
    print('fix 1 applied')
else:
    print('fix 1 already applied or not needed')

# Fix 2: usb_set_configuration() called from HID probe self-deadlocks
# (it tears down the HID device being probed). Use the deferred variant
# and bail out of probe; the interface is re-probed after re-enumeration.
p = os.path.join(d, 'apple-ibridge.c')
s = open(p).read()
old1 = """	ret = usb_set_configuration(udev, target_cv);
	if (ret)
		dev_err(&udev->dev, "MBP14,3: usb_set_configuration(%d) failed: %d\\n",
			target_cv, ret);
	else
		msleep(150); /* let udev settle */
"""
new1 = """	/* Never call usb_set_configuration() from probe: it tears down the HID
	 * device being probed and self-deadlocks. This variant defers the
	 * switch to a workqueue. */
	ret = usb_driver_set_configuration(udev, target_cv);
	if (ret)
		dev_err(&udev->dev, "MBP14,3: usb_driver_set_configuration(%d) failed: %d\\n",
			target_cv, ret);
	else
		ret = 1; /* switch scheduled; caller must not bind this interface */
"""
old2 = """	rc = apple_ib_set_tb_mode(udev, apple_tb_mode);
	if (rc && rc != -ENODEV)"""
new2 = """	rc = apple_ib_set_tb_mode(udev, apple_tb_mode);
	if (rc > 0)
		return -ENODEV; /* config switch scheduled; re-probed afterwards */
	if (rc && rc != -ENODEV)"""
if old1 in s and old2 in s:
    backup(p)
    s = s.replace(old1, new1, 1).replace(old2, new2, 1)
    open(p, 'w').write(s)
    print('fix 2 applied')
else:
    print('fix 2 already applied or code differs')
