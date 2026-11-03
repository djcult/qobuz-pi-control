# qobuz-pi-control

Physical-control companion for [djcult/qobuz-proxy](https://github.com/djcult/qobuz-proxy).

This project deliberately does **not** import qobuz-proxy. It talks to the small semantic HTTP playback-control API exposed by qobuz-proxy, keeping FLIRC and Stream Deck integration isolated from the player and ALSA backend.

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

Optional IR support uses the kernel `ir_toy` driver and RC-5 decoder.
It does not require lircd or changes to qobuz-proxy.

Install `sudo apt install ir-keytable` (provides `ir-ctl` too). Add to your
existing config.toml:

```toml
[ir]
enabled = true
device = "/dev/lirc0"
rc_device = "rc2"
```

Check `ir-keytable` and `ls -l /dev/lirc*` for the current device names;
rc numbers can change after reboot or adding receivers. Update the config
if needed. Stop diagnostic `ir-keytable -t` processes before starting the controller.
If replacing FLIRC, set `enabled = false` in your existing `[flirc]` section
so the same remote press cannot arrive through both adapters.

| Control | Action |
|---|---|
| Audiolab play/pause (`0x1635`) | Qobuz toggle |
| Audiolab previous (`0x1621`) | Qobuz previous |
| Audiolab next (`0x1620`) | Qobuz next |
| Stream Deck key 13 (bottom row, fourth) | CDQ volume down (`0x1611`) |
| Stream Deck key 14 (bottom right) | CDQ volume up (`0x1610`) |

Volume keys send one step per press. They work across all display modes;
the artwork/spectrum continues to fill those keys. Remote volume buttons
continue to operate the CDQ directly. RC-5 toggle bits distinguish new presses
from repeated frames; holding a transport button triggers one action. Receive
actions are suppressed during transmission and for 300 ms afterwards.

Run under your normal service user, without sudo. That user needs read/write
access to the LIRC device and read access to the receiver's input event device.
On Raspberry Pi OS these are usually covered by the `video` and `input` groups:

```bash
sudo usermod -aG video,input "$USER"
```

Check actual device ownership with `ls -l /dev/lirc0 /dev/input/event*`;
log out/in for manual runs, or restart the service for new group membership.
Enabling RC-5 also writes `/sys/class/rc/rc2/protocols`. If this is root-only,
install a udev rule for this particular transceiver:

```bash
sudo tee /etc/udev/rules.d/70-irdroid.rules >/dev/null <<'RULE'
ACTION=="add", SUBSYSTEM=="rc", ATTRS{idVendor}=="04d8", ATTRS{idProduct}=="f58b", RUN+="/bin/chgrp input /sys%p/protocols", RUN+="/bin/chmod g+w /sys%p/protocols"
RULE
sudo udevadm control --reload-rules
```

Unplug/replug the transceiver, recheck its device names, then restart your
controller service. No sudo commands are launched by the controller.

Hardware acceptance check: confirm one remote press toggles playback once,
held next/previous does not skip multiple tracks, and each Stream Deck volume
press changes the CDQ by one step without changing Qobuz playback.
