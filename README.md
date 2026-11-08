# Fedora on a MacBookPro13,2 (2016 13" Touch Bar): Touch Bar, audio, Wi-Fi notes

Notes, patches and boot glue for running Fedora on a 2016 13" MacBook Pro with
Touch Bar (MacBookPro13,2, T1 chip). Covers what I got working and what doesn't.

| Area | Status |
|------|--------|
| Keyboard, trackpad | Work out of the box (`applespi`, mainline) |
| Touch Bar | Lit, Esc + function/media keys work. No graphical display mode. See "Touch Bar" |
| Audio | Works with the `snd_hda_macbookpro` DKMS driver. See "Audio" |
| Wi-Fi | WPA3-only networks do not work (firmware lacks SAE). See "Wi-Fi" |

Tested: Fedora 44 / kernel 7.2.11-200.fc44 (Touch Bar), kernel
7.2.15-300.fc45 (audio), no Secure Boot.

## Credits and upstream

This repo contains patches and setup notes only. The driver itself is not
included. It is based on:

- https://github.com/F13-Kr1pt0n/macbook-pro-touchbar-driver
  (Touch Bar/iBridge updates for Linux 6.15+), a fork of
- https://github.com/marc-git/macbook12-spi-driver, derived from
- https://github.com/roadrunner2/macbook12-spi-driver
  (Ronald Tschalar), originally started by cb22.

Audio uses https://github.com/davidjo/snd_hda_macbookpro (GPL-2.0), installed
unmodified; nothing from it is copied here.

The Touch Bar driver is licensed GPL-2.0. The patches here apply to that code and are
offered under the same licence. All credit for the driver goes to its authors.

# Touch Bar

## Background

- T1 Macs are not covered by t2linux / tiny-dfr / the in-kernel `hid-appletb-*`
  and `appletbdrm` drivers (those target T2).
- Out-of-tree driver used: https://github.com/F13-Kr1pt0n/macbook-pro-touchbar-driver
  (fork of macbook12-spi-driver). Keyboard/trackpad (`applespi`) are in mainline.
- Licence of the driver and of these patches: GPL-2.0.

## Findings

1. **T1 recovery mode.** `lsusb` showing `05ac:1281` ("Apple Mobile Device
   [Recovery Mode]") means the Touch Bar chip is not running. In my case this
   was left over from an OpenCore-patched macOS install. Fix: wipe, reinstall a
   supported macOS (Monterey), confirm the bar works there, then *restart*
   (not shut down) into Linux. The device then shows up as `05ac:8600`.
2. **Build error** on new kernels: `field 'touch' has incomplete type`.
   `struct tb_touch` is embedded before it is defined. Fix 1 in `patches/`.
3. **Module load deadlock.** `appleib_hid_probe()` called
   `usb_set_configuration()`, which destroys the HID device being probed
   (stack: `usb_set_configuration` -> `usbhid_disconnect` -> `hid_device_remove`
   inside `appleib_hid_probe`). `insmod` hangs forever and can't be killed.
   Fix 2: use `usb_driver_set_configuration()` (deferred) and return -ENODEV
   from probe. With `tb_mode_param=keyboard` the config is already correct so
   the switch is skipped.
4. **Module parameter** is `tb_mode_param` (not `tb_mode`).
   `tb_mode=auto` picks the "display" USB config, which stays black on T1.
5. **hid-sensor-hub steals the second iBridge HID interface** (`input3`, the
   display/control one). `apple_ib_tb` only completes setup when it has both
   interfaces, so it must be rebound by hand (done by `scripts/touchbar-up.sh`).
6. **Cold boot** may drop the T1 back to `05ac:1281`. Boot macOS, then restart
   into Linux. Keep a small macOS partition for this (~40 GB).
7. Unrelated kernel WARNING from `iio-sensor-proxy` / `apple_ib_als`
   (`__setup_irq`). Harmless; blacklist `apple_ib_als` if it bothers you.

## Install

```sh
sudo dnf install dkms kernel-devel kernel-headers gcc make git
git clone https://github.com/F13-Kr1pt0n/macbook-pro-touchbar-driver.git
python3 patches/apply-fixes.py macbook-pro-touchbar-driver

sudo mkdir -p /usr/src/appleibridge-0.1
sudo cp -r macbook-pro-touchbar-driver/. /usr/src/appleibridge-0.1
sudo dkms add -m appleibridge -v 0.1
sudo dkms build -m appleibridge -v 0.1
sudo dkms install -m appleibridge -v 0.1

sudo cp modprobe/*.conf /etc/modprobe.d/
sudo install -m 755 scripts/touchbar-up.sh /usr/local/sbin/
sudo cp systemd/touchbar-up.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable touchbar-up.service
sudo reboot        # warm reboot, not shutdown
```

Note: the blacklist file stops udev autoloading `apple_ibridge`;
`touchbar-up.service` loads it explicitly. Loading from the DKMS post-install
hook while an old build was stuck caused a hang during testing.

## Configuration

Options live in `/etc/modprobe.d/apple-ib.conf` and apply the next time the
modules load (reboot, or unload with
`sudo modprobe -r apple-ib-als apple-ib-tb apple-ibridge` and then
`sudo systemctl restart touchbar-up.service`).

### Function key mode (`fnmode`)

| Value | Behaviour |
|-------|-----------|
| 0 | Function keys only (F1-F12) |
| 1 | Media keys by default; hold Fn for F-keys |
| 2 | F-keys by default; hold Fn for media keys |
| 3 | Media/special keys only |

### Battery saving (`idle_timeout`, `dim_timeout`)

- `idle_timeout=N` (N > 0): turn the bar off after N seconds without input.
  It turns back on at the next key, trackpad or touch event.
  `0` = off, `-1` = always on, `-2` = disable the bar entirely.
- `dim_timeout=N` (N > 0): dim after N seconds. `-1` = never dim,
  `0` = always dimmed, `-2` = calculate from `idle_timeout` (default).

Example: `options apple-ib-tb idle_timeout=60 dim_timeout=15 fnmode=1`

Tested on the author's machine: `idle_timeout=-1`, `dim_timeout=-1` and
switching `fnmode` between 0 and 3. The example values above are the shipped
defaults in `modprobe/apple-ib.conf` and have not been verified in detail.

### Changing values at runtime

The live values are files next to the HID device:

```sh
D=$(dirname "$(find /sys -name idle_timeout -path '*8600*' 2>/dev/null | head -1)")
echo 30 | sudo tee $D/idle_timeout
echo 0  | sudo tee $D/fnmode
```

Runtime changes are lost on reload. The device number in the path changes
between boots, which is why the snippet uses `find`.

## Generating patch files

If you prefer real `.patch` files, run in the patched source dir
(the `.orig` backups are made by `apply-fixes.py`):

```sh
diff -u --label a/apple-ib-tb.c --label b/apple-ib-tb.c apple-ib-tb.c.orig apple-ib-tb.c > 0001-fix-tb_touch-incomplete-type.patch
diff -u --label a/apple-ibridge.c --label b/apple-ibridge.c apple-ibridge.c.orig apple-ibridge.c > 0002-fix-probe-deadlock.patch
```

## Untested

Suspend/resume (try `systemctl restart touchbar-up.service` after wake),
display mode, the touch shim, and the ambient light sensor.

# Audio

Symptom: the sound card is detected (`aplay -l` shows `CS8409 Analog`,
PipeWire has a default sink) but nothing comes out. `pw-play` returns no error,
and `amixer -c 0 scontrols` lists only PCM, Mic, IEC958 and Internal Mic, with
no Speaker or Master control. `dmesg` shows the stock `snd_hda_codec_cs8409`
binding without the Apple-specific setup.

Fix: install the patched Cirrus CS8409 driver via DKMS.

1. `egorenar/snd-hda-codec-cs8409` did **not** build on kernel 7.2. The HDA core
   dropped `patch_ops` from `struct hda_codec` and changed `hda_codec_ops`
   (errors: `has no member named 'free'`, `has no member named 'patch_ops'`).
   The same errors are reported on 6.17+. It needs porting to the new API.
2. `davidjo/snd_hda_macbookpro` builds and works on 7.2.15 (its log notes
   kernels from 7.0 onwards are allowed, with a warning that later kernels may
   need changes):

```sh
sudo dnf install dkms kernel-devel kernel-headers gcc make patch wget tar xz git
git clone https://github.com/davidjo/snd_hda_macbookpro.git ~/snd_hda_macbookpro
cd ~/snd_hda_macbookpro
sudo ./install.cirrus.driver.sh -i
sudo reboot
```

Notes:

- The script downloads the mainline kernel source (150 MB+) for your kernel
  version and patches the HDA sources, so you need a connection.
- Keep the cloned folder. DKMS uses a symlink,
  `/usr/src/snd_hda_macbookpro-0.1`, that points into it.
- The script's final `ls` of `updates/dkms` prints "No such file or directory"
  on Fedora because DKMS puts the module in `extra/`. That is not a failure.
  Check with `sudo dkms status` and
  `find /lib/modules/$(uname -r) -name 'snd-hda-codec-cs8409*'`.
- After a kernel update, run `sudo dkms status`. If audio disappears, a missing
  or failed rebuild is the first thing to check. Older kernels stay selectable
  in GRUB.
- Remove with `sudo ./install.cirrus.driver.sh -r` and reboot. The original
  module is restored.
- Microphone and headset behaviour is not tested here. The driver's own notes
  say input is less complete than output.

# Wi-Fi

Hardware: Broadcom BCM43602, driver `brcmfmac`. The firmware loaded under Linux
is from Nov 2015 (version 7.35.177.61). `iw phy` lists no `SAE` or `SAE_OFFLOAD`
in the extended features, only PSK and 802.1X handshakes, so **WPA3-only
networks cannot be joined**. This is a firmware limit, not a setting.

Workarounds: set the router to WPA2/WPA3 mixed mode, use a WPA2 network
(guest SSID, phone hotspot), USB tethering, or a USB Wi-Fi adapter.

Unresolved: whether macOS (which uses Apple's own firmware) connects to WPA3
on this chip, and whether that firmware could be used with `brcmfmac`. I did
not test that.
