"""IR Droid support through Linux rc-core and v4l-utils command-line tools."""

import asyncio
import logging
import re
import time

from .config import IRConfig

logger = logging.getLogger(__name__)
RX_ACTIONS = {0x1635: "toggle", 0x1621: "previous", 0x1620: "next"}
TX_CODES = {"volume_down": 0x1611, "volume_up": 0x1610}
FRAME = re.compile(r"lirc protocol\(rc5\): scancode = (0x[0-9a-fA-F]+)(.*)")


class PressFilter:
    """Accept new RC-5 presses, suppressing a held button's repeat frames."""

    def __init__(self):
        self.last = None
        self.at = float("-inf")

    def accept(self, code, toggle, now):
        press = (code, toggle)
        fresh = press != self.last or now - self.at > 0.3
        self.last, self.at = press, now
        return fresh


class Infrared:
    def __init__(self, config: IRConfig):
        self.config = config
        self.lock = asyncio.Lock()
        self.ignore_until = 0.0

    async def send(self, action):
        if not self.config.enabled:
            return
        async with self.lock:
            self.ignore_until = float("inf")
            process = None
            try:
                process = await asyncio.create_subprocess_exec(
                    "ir-ctl", "-d", self.config.device,
                    f"--scancode=rc5:0x{self.config.transmit[action]:04x}",
                    stderr=asyncio.subprocess.PIPE,
                )
                _, error = await asyncio.wait_for(process.communicate(), 3)
                if process.returncode:
                    raise RuntimeError(error.decode().strip())
            finally:
                if process is not None and process.returncode is None:
                    process.kill()
                    await process.wait()
                self.ignore_until = time.monotonic() + 0.3

    async def receive(self, dispatch):
        # ir-keytable enables the kernel RC-5 decoder and emits decoded frames.
        process = await asyncio.create_subprocess_exec(
            "stdbuf", "-oL", "ir-keytable", "-s", self.config.rc_device,
            "-p", "rc-5", "-t", stdout=asyncio.subprocess.PIPE,
        )
        queue = asyncio.Queue(maxsize=4)

        async def consume():
            while True:
                action = await queue.get()
                try:
                    await dispatch(action)
                except Exception:
                    logger.exception("IR action failed: %s", action)

        worker = asyncio.create_task(consume())
        presses = PressFilter()
        try:
            while line := await process.stdout.readline():
                match = FRAME.search(line.decode(errors="replace"))
                if not match:
                    continue
                code = int(match[1], 16)
                now = time.monotonic()
                fresh = presses.accept(code, "toggle=1" in match[2], now)
                if fresh and now >= self.ignore_until and code in self.config.receive:
                    # Keep consuming repeats while the HTTP request is running.
                    # A bounded queue avoids accumulating actions during outages.
                    if not queue.full():
                        queue.put_nowait(self.config.receive[code])
            raise RuntimeError(f"IR receiver exited: {await process.wait()}")
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            if process.returncode is None:
                process.terminate()
                await process.wait()
