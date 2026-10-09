"""qobuz-pi-control service entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging

from .client import QobuzProxyClient
from .config import load_config
from .flirc import run_flirc
from .streamdeck import run_streamdeck

logger = logging.getLogger(__name__)


async def run(config_path: str, no_flirc: bool = False, no_streamdeck: bool = False) -> None:
    config = load_config(config_path)

    async with QobuzProxyClient(
        config.proxy.base_url,
        config.proxy.speaker_id,
        config.proxy.timeout_seconds,
    ) as client:

        async def dispatch(action: str) -> None:
            try:
                result = await client.action(action)
                logger.info(
                    "%s: %s (%s)",
                    action,
                    "accepted" if result.accepted else "rejected",
                    result.speaker.get("status", "unknown"),
                )
            except Exception:
                logger.exception("Control action failed: %s", action)

        tasks = []
        if config.flirc.enabled and not no_flirc:
            tasks.append(asyncio.create_task(run_flirc(config.flirc, dispatch)))
        if config.streamdeck.enabled and not no_streamdeck:
            tasks.append(asyncio.create_task(run_streamdeck(config.streamdeck, dispatch, client.status)))

        if not tasks:
            raise RuntimeError("No control adapters enabled")

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()


def main() -> None:
    parser = argparse.ArgumentParser(description="Physical controls for qobuz-proxy")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--no-flirc", action="store_true")
    parser.add_argument("--no-streamdeck", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run(args.config, args.no_flirc, args.no_streamdeck))


if __name__ == "__main__":
    main()
