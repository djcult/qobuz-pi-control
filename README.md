# qobuz-pi-control

Physical-control companion for [djcult/qobuz-proxy](https://github.com/djcult/qobuz-proxy).

This project deliberately does **not** import qobuz-proxy. It talks to the small semantic HTTP playback-control API exposed by the `player-control-api` branch, keeping FLIRC and Stream Deck integration isolated from the player and ALSA backend.

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

## Service

The included `systemd/qobuz-pi-control.service` assumes installation in `/opt/qobuz-pi-control` with its virtual environment at `.venv`.

The control process is intentionally stateless. qobuz-proxy remains authoritative for playback state and the Qobuz queue.
