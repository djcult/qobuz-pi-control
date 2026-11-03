# qobuz-pi-control

Physical-control companion for [djcult/qobuz-proxy](https://github.com/djcult/qobuz-proxy).

This project deliberately does **not** import qobuz-proxy. It talks to the small semantic HTTP playback-control API exposed by qobuz-proxy, keeping IR Droid, FLIRC and Stream Deck integration isolated from the player and ALSA backend.

## Architecture

```
FLIRC (USB keyboard) ──┐
                      ├── qobuz-pi-control ──HTTP──> qobuz-proxy ──> ALSA ──> DAC
Stream Deck (USB HID) ─┘
```

## Supported actions

- play
- pause
- toggle
- next
- previous

## Install and configure

Requires Python 3.11+ and `uv`. This fork is deployed alongside
[`qobuz-proxy`](https://github.com/djcult/qobuz-proxy/blob/alsa-dev/README.md#raspberry-pi-alsa--systemd)
on the same Raspberry Pi.

For a new installation, clone the repository to `~/src/qobuz-pi-control`
and create the local configuration. If already installed and working, **keep
your existing `config.toml`**.

```bash
# New installations only:
mkdir -p ~/src
git clone https://github.com/djcult/qobuz-pi-control.git ~/src/qobuz-pi-control

cd ~/src/qobuz-pi-control
git switch dev
git pull --ff-only
uv sync --no-dev --extra streamdeck

# New installations only; edit the file for your Qobuz speaker and hardware:
cp config.example.toml config.toml
```

The default `config.toml` expects the proxy at `127.0.0.1:8689`
and speaker ID `cdq2`. FLIRC can emit otherwise-unused F13–F17 keys.
The Stream Deck requires USB/HID access; FLIRC needs `/dev/input/event*`
access. Arrange udev permissions or appropriate groups for the service user.

To test the controller manually **before** enabling systemd:

```bash
cd ~/src/qobuz-pi-control
.venv/bin/qobuz-pi-control --config config.toml
```

The `--no-flirc` and `--no-streamdeck` flags disable individual adapters.
Stop the manual process before starting the systemd service.

## Raspberry Pi systemd service

The checked-in [systemd/qobuz-pi-control.service](systemd/qobuz-pi-control.service)
runs the controller as the same unprivileged Linux user as qobuz-proxy.
It assumes `~/src/qobuz-pi-control`, its local `.venv`, and `config.toml`;
edit the template if your install differs.

The proxy must be installed and running with its companion
[`qobuz-proxy.service`](https://github.com/djcult/qobuz-proxy/blob/alsa-dev/contrib/qobuz-proxy.service).
The controller connects to the HTTP API (`http://127.0.0.1:8689` by default)
and receives the optional PCM spectrum feed over `/tmp/qobuz-pcm.sock`.

### Install and enable

```bash
cd ~/src/qobuz-pi-control
git switch dev
git pull --ff-only
uv sync --no-dev --extra streamdeck
sudo apt-get install -y curl
test -f config.toml

# Convert the tracked template into a unit with your actual Linux user/home.
sed -e "s|@USER@|$(id -un)|g" \
    -e "s|@HOME@|$HOME|g" \
    systemd/qobuz-pi-control.service |
    sudo tee /etc/systemd/system/qobuz-pi-control.service >/dev/null

sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/qobuz-pi-control.service
sudo systemctl enable --now qobuz-pi-control.service
systemctl status qobuz-pi-control.service
```

The service waits for the proxy's `GET /api/speakers` to succeed **before**
launching the controller. `After=qobuz-proxy.service` alone only orders process
startup; it does **not** mean the HTTP API is ready. The readiness check uses
`curl` and retries for up to 90 seconds. If it times out, systemd restarts the
service after five seconds and checks again. If your proxy uses a non-default
address/port, update both `config.toml` and the readiness URL in the unit.

After the controller has started, an API outage **does not normally kill the
controller**: its polling loop catches HTTP errors and keeps retrying, showing
offline feedback when appropriate. The service-level retry handles failures
during startup (including device-initialisation failures).

### USB / input permissions

The service user needs access to the Stream Deck HID device and the FLIRC
`/dev/input/event*` device (udev rules or appropriate group membership).
The same Linux user should run both services: the PCM receiver binds
`/tmp/qobuz-pcm.sock` with mode `0600`. The proxy and controller must share
the same `/tmp` namespace; **do not use `PrivateTmp=true` in either unit**.

### Operate and diagnose

```bash
sudo systemctl restart qobuz-pi-control
journalctl -u qobuz-pi-control -f
journalctl -u qobuz-proxy -u qobuz-pi-control -f
systemctl is-active qobuz-proxy qobuz-pi-control
ls -l /tmp/qobuz-pcm.sock
```

Stop manually launched controller instances before enabling the service: only
one process can own the Stream Deck. Restart the service after `git pull`
to load new code. See the proxy README for its own service installation and
PCM-monitor environment variable.

The control process is intentionally stateless. QobuzProxy remains authoritative
for playback state and the Qobuz queue.


## IR Droid v3 / Audiolab 8300CDQ

The IR Droid USB transceiver v3 receives Audiolab remote commands and sends
volume commands to the CDQ. Playback buttons call the existing Qobuz HTTP API;
volume control goes directly to the CDQ over IR. No proxy changes or lircd
daemon are needed. IR is disabled by default.

### Install and identify the device

On the Pi:

```bash
sudo apt install ir-keytable
lsusb
sudo dmesg | tail -40
ir-keytable
ls -l /dev/lirc*
```

The tested device is USB ID `04d8:f58b`, using the kernel `ir_toy` driver.
Its log reports a raw IR receiver and transmitter. It appeared as
`/dev/lirc0` and `rc2`; a `/dev/ttyACM*` serial device is not required.
Device numbers can change after reboot or reconnecting: use the values
reported on your Pi in the configuration below.

### Permanent permissions

From the repository folder, install the supplied device-specific udev rule.
These commands assume the controller runs as `pi`; substitute your service
user if different.

```bash
sudo install -m 0644 systemd/70-irdroid.rules /etc/udev/rules.d/70-irdroid.rules
sudo usermod -aG input pi
sudo udevadm control --reload-rules
sudo reboot
```

The rule grants the input group read/write access to the transceiver's LIRC
device, read access to its input event device, and write access to its sysfs
protocols file. It is reapplied on boot and reconnect. The reboot applies both
the rule and group membership. Alternatively, unplug/replug the IR Droid,
log out/in, and restart the service. Run the controller without sudo.

### Configure devices and mappings

Keep your existing `config.toml`. Add the following tables, or edit them if
already present; do not duplicate TOML table headers:

```toml
[ir]
enabled = true
device = "/dev/lirc0"
rc_device = "rc2"

[ir.receive]
"0x1635" = "toggle"
"0x1621" = "previous"
"0x1620" = "next"

[ir.transmit]
volume_down = 0x1611
volume_up = 0x1610

[streamdeck.buttons]
"0" = "previous"
"1" = "toggle"
"2" = "next"
"4" = "display"
"10" = "volume_down"
"11" = "volume_up"
```

| Control | Default action |
|---|---|
| Remote play/pause (`0x1635`) | Qobuz toggle |
| Remote previous (`0x1621`) | Qobuz previous |
| Remote next (`0x1620`) | Qobuz next |
| Bottom-left Stream Deck key (10) | CDQ volume down (`0x1611`) |
| Second bottom-row key (11) | CDQ volume up (`0x1610`) |
| Top-right key (4) | Cycle display mode |

Stream Deck keys are numbered 0–14, left to right, top to bottom.
Supported button actions are `play`, `pause`, `toggle`, `previous`, `next`,
`volume_down`, `volume_up` and `display`. IR receive mappings support the five
playback actions; transmit mappings require both volume commands.
Each mapping table replaces its own defaults completely; an empty
`[streamdeck.buttons]` or `[ir.receive]` disables those bindings.
Omitted tables retain the defaults. Volume buttons are inactive when IR
is disabled.

Control icons follow configured positions in the full-info artwork mode.
Volume icons use white speaker minus/plus glyphs on translucent circles to
match the track controls. Other display modes retain their clean visuals,
but buttons still work. Keys 13/14 display quality/time, so avoid placing
control icons there.

Volume sends one step per press. Remote volume buttons still control the
CDQ directly. RC-5 toggle state filters repeated frames from a held transport
button; reception actions are suppressed during IR transmission and for
300 ms afterwards.

If replacing FLIRC, edit the existing `[flirc]` section to set
`enabled = false`, or use `--no-flirc` for interactive testing. This prevents
one remote press arriving through two adapters. Local `config.toml` is not
updated by `git pull`; restart the controller after editing it.

### Run interactively

Stop the controller service first so it releases the Stream Deck:

```bash
sudo systemctl stop qobuz-pi-control
cd ~/src/qobuz-pi-control
source .venv/bin/activate
qobuz-pi-control --config config.toml --no-flirc
```

If your installed unit has a different name, such as `qobuzcontrol`, use
that name in systemctl commands. Press Ctrl+C to stop. For IR-only testing:

```bash
qobuz-pi-control --config config.toml --no-flirc --no-streamdeck
```

For normal systemd operation, disable FLIRC in config if no longer needed,
stop the interactive process, then restart your installed controller service.

### Learn and test remote commands

Stop the controller before running these diagnostics. To view raw pulses,
point the remote at the IR Droid and press a button:

```bash
sudo ir-ctl -d /dev/lirc0 --receive
```

Press Ctrl+C, then decode RC-5 commands:

```bash
sudo ir-keytable -s rc2 -p rc-5 -t
```

The Audiolab remote reports lines such as
`lirc protocol(rc5): scancode = 0x1635 toggle=1`. Repeated frames during one
press retain the toggle state; a new press changes it. Put the observed
code/action pairs in `[ir.receive]`.

Press Ctrl+C and point the transceiver towards the CDQ to test transmission:

```bash
sudo ir-ctl -d /dev/lirc0 --scancode=rc5:0x1611
```

This should lower the volume by one step. After permissions are installed,
repeat without sudo to verify access for the controller user. Stop diagnostic
listeners before restarting the controller.

### Troubleshooting and acceptance checks

- **Permission denied on /sys/class/rc/rc2/protocols:** check that the supplied
  rule is installed, the device was reconnected or rebooted, and `id pi`
  includes input. Verify the configured rc number. A double slash before
  protocols in the error path is harmless.
- **Receive/transmit permissions:** inspect `ls -l /dev/lirc0 /dev/input/event*`.
  The IR Droid devices should be accessible to the controller's input group.
- **Stream Deck feature-report error:** stop other controller processes and
  the systemd service; unplug/reconnect the Elgato Stream Deck, then retry.
  This is separate from IR protocol permissions.
- **No remote actions:** check the device names, RC-5 codes and `[ir].enabled`,
  and try the IR-only command above.
- **Final check:** one remote play/pause press should toggle once, holding
  next/previous should not skip multiple tracks, and each Stream Deck volume
  press should change the CDQ by one step without changing Qobuz playback.
