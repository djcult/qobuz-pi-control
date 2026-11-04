"""Control USB Litra Beams through the separately installed litra CLI."""

import asyncio
import os


class Litra:
    def __init__(self, executable="/usr/local/bin/litra"):
        self.executable = executable
        self.lock = asyncio.Lock()
        # Beam limits: 30–400 lumens. None means unknown after service startup.
        self.brightness = None

    async def _run(self, *args):
        process = await asyncio.create_subprocess_exec(
            self.executable, *args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "LITRA_DISABLE_UPDATE_CHECK": "1"},
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
        if process.returncode:
            raise RuntimeError(stderr.decode(errors="replace").strip() or "litra failed")
        return stdout

    async def adjust(self, increase):
        # Serialize read/modify/write so rapid presses cannot lose a step.
        async with self.lock:
            target = ("--device-type", "beam")
            minimum, maximum, step = 30, 400, 20
            # Never query hardware: some Beams block indefinitely on HID reads.
            # Establish a known state on the first press after startup.
            if self.brightness is None or self.brightness == 0:
                if increase:
                    await self._run("brightness", *target, "--value", str(minimum))
                    await self._run("on", *target)
                    self.brightness = minimum
                elif self.brightness is None:
                    await self._run("off", *target)
                    self.brightness = 0
                return
            value = self.brightness + (step if increase else -step)
            if value < minimum:
                await self._run("off", *target)
                self.brightness = 0
            else:
                value = min(value, maximum)
                await self._run("brightness", *target, "--value", str(value))
                # Explicitly turn on so external power-off doesn't prevent control.
                await self._run("on", *target)
                self.brightness = value
