#!/usr/bin/env python3
"""Port apple-ibridge.c from struct acpi_driver (removed in Linux 7.3) to a
platform_driver, keeping the old code for kernels < 7.3.

Run AFTER apply-fixes.py:  python3 fix-acpi-driver-7.3.py /path/to/source
Idempotent. Keeps apple-ibridge.c.pre73 as a backup on first run.
"""
import re, shutil, sys, os

d = sys.argv[1] if len(sys.argv) > 1 else '.'
p = os.path.join(d, 'apple-ibridge.c')
s = open(p).read()

if 'APPLEIB_PLATFORM_DRIVER' in s:
    print('already applied')
    sys.exit(0)

def sub1(pattern, repl, text, flags=0):
    new, n = re.subn(pattern, lambda m: repl, text, count=1, flags=flags)
    assert n == 1, 'pattern not found: ' + pattern
    return new

# 1. compat header block after <linux/acpi.h>
hdr = '''#include <linux/acpi.h>
#include <linux/version.h>
#if LINUX_VERSION_CODE >= KERNEL_VERSION(7,3,0)
/* struct acpi_driver was removed; bind as a platform driver instead. */
#include <linux/platform_device.h>
#define APPLEIB_PLATFORM_DRIVER 1
#define appleib_dev_drvdata(dev)	dev_get_drvdata(dev)
#else
#define appleib_dev_drvdata(dev)	acpi_driver_data(to_acpi_device(dev))
#endif
'''
s = sub1(r'#include <linux/acpi.h>\n', hdr, s)

# 2. alloc helper: take the device that owns the devres
s = sub1(r'appleib_alloc_device\(struct acpi_device \*acpi_dev\)',
         'appleib_alloc_device(struct acpi_device *acpi_dev,\n\t\t\t\t\t\t    struct device *dev)', s)
s = sub1(r'devm_kzalloc\(&acpi_dev->dev,', 'devm_kzalloc(dev,', s)

# 3. probe
m = re.search(r'static int appleib_probe\(struct acpi_device \*acpi\)\s*\{\n', s)
assert m, 'probe signature not found'
e = s.index('static void appleib_remove(')
probe = s[m.start():e]
sig = '''#ifdef APPLEIB_PLATFORM_DRIVER
static int appleib_probe(struct platform_device *pdev)
{
	struct acpi_device *acpi = ACPI_COMPANION(&pdev->dev);
	struct device *pdev_dev = &pdev->dev;
#else
static int appleib_probe(struct acpi_device *acpi)
{
	struct device *pdev_dev = &acpi->dev;
#endif
'''
body = probe[m.end() - m.start():]
assert body.count('&acpi->dev') >= 1
body = body.replace('&acpi->dev', 'pdev_dev')
assert 'ib_dev = appleib_alloc_device(acpi);' in body
body = body.replace('ib_dev = appleib_alloc_device(acpi);',
    '''#ifdef APPLEIB_PLATFORM_DRIVER
	if (!acpi)
		return -ENODEV;
#endif
	ib_dev = appleib_alloc_device(acpi, pdev_dev);''', 1)
assert 'acpi->driver_data = ib_dev;' in body
body = body.replace('acpi->driver_data = ib_dev;',
    '''#ifdef APPLEIB_PLATFORM_DRIVER
	platform_set_drvdata(pdev, ib_dev);
#else
	acpi->driver_data = ib_dev;
#endif''', 1)
s = s[:m.start()] + sig + body + s[e:]

# 4. remove
rm = r'static void appleib_remove\(struct acpi_device \*acpi\)\s*\{\n\s*struct appleib_device \*ib_dev = acpi_driver_data\(acpi\);\n'
new_rm = '''#ifdef APPLEIB_PLATFORM_DRIVER
static void appleib_remove(struct platform_device *pdev)
{
	struct appleib_device *ib_dev = platform_get_drvdata(pdev);
#else
static void appleib_remove(struct acpi_device *acpi)
{
	struct appleib_device *ib_dev = acpi_driver_data(acpi);
#endif
'''
s = sub1(rm, new_rm, s)

# 5. PM callbacks
n = s.count('ib_dev = acpi_driver_data(to_acpi_device(dev));')
assert n == 2, 'expected 2 PM uses, found %d' % n
s = s.replace('ib_dev = acpi_driver_data(to_acpi_device(dev));',
              'ib_dev = appleib_dev_drvdata(dev);')

# 6. driver registration
drv = r'static struct acpi_driver appleib_driver = \{.*?\n\};\n\s*module_acpi_driver\(appleib_driver\)\n'
m = re.search(drv, s, re.S)
assert m, 'acpi_driver block not found'
old = m.group(0)
new = '''#ifdef APPLEIB_PLATFORM_DRIVER
static struct platform_driver appleib_driver = {
	.probe		= appleib_probe,
	.remove		= appleib_remove,
	.driver		= {
		.name			= "apple-ibridge",
		.acpi_match_table	= appleib_acpi_match,
		.pm			= &appleib_pm,
	},
};

module_platform_driver(appleib_driver);
#else
''' + old + '''#endif
'''
s = s.replace(old, new, 1)

if not os.path.exists(p + '.pre73'):
    shutil.copy(p, p + '.pre73')
open(p, 'w').write(s)
print('applied')
