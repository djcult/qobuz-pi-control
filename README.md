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

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/djcult/qobuz-pi-control.git
cd qobuz-pi-control
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

Stream Deck support is optional:

```bash
pip install -e '.[streamdeck]'
```

## Configure

Copy `config.example.toml` to `config.toml`. The default assumes qobuz-proxy is on the same Pi at port 8689 and the speaker id is `cdq2`.

FLIRC should be configured to emit otherwise-unused keys (F13-F17 by default). This makes the FLIRC appear as an ordinary Linux keyboard while keeping its mappings away from normal typing.

## Run

```bash
qobuz-pi-control --config config.toml
```

Use `--no-flirc` or `--no-streamdeck` to disable an adapter.

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
