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


## FLIRC receiver setup

FLIRC is an optional USB IR receiver that presents as a keyboard. It receives
remote presses; it cannot transmit volume commands to the amplifier.
Use FLIRC or IR Droid for a given remote's playback buttons to avoid duplicate
actions. Disable an unused adapter in config.toml.

### Pair the remote and choose keyboard keys

1. Install the manufacturer's [FLIRC software](https://flirc.tv/) on a computer
   and plug the FLIRC receiver into that computer.
2. In the FLIRC keyboard controller, select a keyboard key and press the
   remote button you want to associate with it. Repeat for each action.
   For a simple GUI setup, use F1–F5 and the matching configuration below.
3. Move the programmed receiver to the Pi. The associations are stored in
   the receiver; the FLIRC application does not need to run on the Pi.

Edit your existing config.toml section:

```toml
[flirc]
enabled = true
device = "auto"
grab = false
play_pause = "KEY_F1"
next = "KEY_F2"
previous = "KEY_F3"
play = "KEY_F4"
pause = "KEY_F5"
```

These must match the keys you taught FLIRC. The shipped example instead uses
F13–F17 to avoid collisions with ordinary keyboard shortcuts; retain those
if your receiver is already programmed that way. Unused play/pause actions
need not be learned. Choose keys that other applications will not act on,
or enable grab for exclusive access to this receiver.

### Permissions and testing

```bash
sudo usermod -aG input pi
```

Log out/in or reboot, then stop any running controller service before testing.
FLIRC input event devices must be readable by pi. Check with:

```bash
ls -l /dev/input/by-id/
ls -l /dev/input/event*
```

Auto-discovery selects an input device whose name contains flirc. If necessary,
set device to its keyboard event path, preferably the stable
/dev/input/by-id/...-event-kbd symlink shown on your Pi. Do not use an invented
path. For FLIRC-only testing, set enabled = false in the existing [ir] section:

```bash
.venv/bin/qobuz-pi-control --config config.toml --no-streamdeck
```

Press the learned buttons and watch the accepted/rejected action logs. If
nothing happens, optionally install evtest with sudo apt install evtest,
run sudo evtest, choose the FLIRC keyboard and verify the emitted KEY_F*
names match the config. Stop evtest before retrying. If auto-discovery fails,
check the receiver is connected and the user can read its input device.

## Stream Deck setup

The tested hardware is an Elgato Stream Deck MK.2 with 15 buttons, arranged
in five columns and three rows. Connect it directly to the Pi by USB.
The controller currently opens the first Stream Deck it finds; the device
config field does not select a particular deck. The visual layout assumes
a 5-by-3 deck.

### Install and grant USB access

From the repository folder:

```bash
sudo apt install libhidapi-libusb0
uv sync --no-dev --extra streamdeck
sudo groupadd -f streamdeck
sudo usermod -aG streamdeck pi
sudo tee /etc/udev/rules.d/70-streamdeck.rules >/dev/null <<'RULE'
SUBSYSTEM=="usb", ATTR{idVendor}=="0fd9", GROUP="streamdeck", MODE="0660"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0fd9", GROUP="streamdeck", MODE="0660"
RULE
sudo udevadm control --reload-rules
```

These rules cover Elgato USB devices (vendor 0fd9). Log out/in and
unplug/reconnect the Stream Deck, or reboot. This gives the service user
access without running the controller as root.

### Configuration and buttons

Edit the existing [streamdeck] section, preserving your preferred spectrum
settings:

```toml
[streamdeck]
enabled = true
device = "auto"
brightness = 35
spectrum_fps = 15
spectrum_delay_ms = 150
spectrum_gain = 1.4
spectrum_bands = 64

[streamdeck.buttons]
"0" = "previous"
"1" = "toggle"
"2" = "next"
"4" = "display"
"10" = "volume_down"
"11" = "volume_up"
```

| Row | Button indices, left to right | Default controls |
|---|---|---|
| Top | 0, 1, 2, 3, 4 | Previous, play/pause, next, unused, display mode |
| Middle | 5, 6, 7, 8, 9 | No default actions |
| Bottom | 10, 11, 12, 13, 14 | Volume down, volume up, unused, unused, unused |

Volume requires the enabled IR Droid adapter described below.
The display button cycles artwork + all info, artwork + title,
spectrum + title, and spectrum only. Controls remain active in all modes.
Full-info artwork displays control icons; the other modes hide those overlays.
The artwork and metadata are fetched from the proxy's playback status.

Set `spectrum_palette` in your existing `[streamdeck]` section to
`"classic"` (default rainbow), `"retro_orange"` (amber bars, pale yellow peaks)
or `"retro_green"` (phosphor green bars, mint peaks). Retro schemes use a
subtly tinted near-black background and one bar colour across frequencies.
Both spectrum display modes use the selected palette. Restart after changing it.

Set `spectrum_bands` to any integer from 1 to 256, for example 24, 48, 80 or 96.
Fewer bands give wider bars; more bands give finer visual subdivisions and
increase FFT processing work. High counts can share FFT bins and crowd the
display, so they do not necessarily reveal more frequency detail.

Spectrum additionally requires the proxy's PCM monitor feed at
/tmp/qobuz-pcm.sock. See the proxy installation instructions linked above.
Both services must run as the same user and share /tmp. An absent feed leaves
the spectrum silent; it does not disable the playback buttons.

### Interactive test and troubleshooting

Stop the installed service first (use its actual unit name if different):

```bash
sudo systemctl stop qobuz-pi-control
.venv/bin/qobuz-pi-control --config config.toml --no-flirc
```

Set [ir].enabled = false for a Stream Deck-only test, or leave it enabled to
test volume as well. Press Ctrl+C to stop before restarting the service.

- If the StreamDeck Python package is missing, rerun uv sync with
  --extra streamdeck.
- If no deck is found or USB access is denied, check lsusb, the udev rules
  and pi's group membership.
- If reset fails with a feature-report error, stop all competing controller
  instances and unplug/reconnect the Elgato Stream Deck before retrying.
- An IR protocols permission error concerns the IR Droid, not the Stream Deck;
  follow the separate permissions instructions below.

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

## Litra Beam brightness

Install the ARM64 `litra` CLI as `/usr/local/bin/litra` and configure its udev
permissions so the service user can run `litra on` without sudo.
No Rust runtime or additional Python dependencies are needed.

Add these entries to your existing `[streamdeck.buttons]` table in `config.toml`
(the table replaces the defaults, so keep your other mappings):

```toml
"13" = "light_down" # Bottom row, button 4
"14" = "light_up"   # Bottom row, button 5
```

Sun minus/plus icons appear on pages 1 and 3 and the idle display, replacing the
quality/time labels on these keys. Pages 2 and 4 retain their clean displays;
buttons work on every page. Each press adjusts by 5% of maximum lumen output,
clamped at maximum. Down below minimum switches off; up while off sets minimum
brightness and switches on. Down while off does nothing. The controller tracks its own level and controls all accessible USB Litra Beams.
It avoids status queries because some Beams hang on USB reads. After a service
restart, the first up press sets minimum brightness and turns on; the first down
press turns off. Changes made with physical buttons are not synchronized.
Restart `qobuz-pi-control` after editing configuration.

## Recently played albums

The page button now cycles through a fifth page, **Recent Albums**, after the
four existing artwork/spectrum views. It shows up to 14 distinct albums
(one cover per button), reserving the configured page button for navigation.
Titles have a dark backing; artwork loads in the background. The navigation
button shows only the triangle, including when history is empty.

History is collected while this controller is running and the configured proxy
speaker reports `playing`. Listening started from the Qobuz app is included,
as are albums heard within playlists. Unpinned albums move to the front of the
recent list when listening returns to them. Up to 50 albums, including pins,
are saved atomically in
`~/.local/state/qobuz-pi-control/recent-albums.json` (or under `$XDG_STATE_HOME`),
so the history survives restarts. Run the service as your normal user to keep
manual and service history in the same place. It does not import earlier Qobuz
account history.

Tap and release a cover to request the complete album from its beginning; the
page stays open. Hold a cover for **0.7 seconds** to pin or unpin it without
starting playback. Pinned covers show a small gold pushpin and stay at the front
in pinning order; new listening rotates only the unpinned albums through the
remaining buttons. Pins survive restarts and are never evicted by new listening.
Unpinning puts the album at the front of the rotating recent list. Set
`album_hold_seconds` under `[streamdeck]` to tune the hold duration (0.3–5.0 seconds).
Changing pages cancels any pending album press.

The navigation key shows only the triangle. Other
keys on this page select albums; volume/light/media mappings still apply on
the existing pages. Repeated presses are ignored while a launch is in flight.

Requires the proxy update exposing album IDs and
`POST /api/speakers/{speaker_id}/albums/{album_id}/play`. Select your speaker in
Qobuz Connect first. **Album launch is experimental until tested on a real
session**; a rejected or unacknowledged cloud request is logged without changing
the navigation button or starting a separate local playback queue.
