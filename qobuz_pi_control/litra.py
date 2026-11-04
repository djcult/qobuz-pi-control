"""Control USB Litra Beams through the separately installed litra CLI."""

import asyncio
import json
import os


class Litra:
    def __init__(self, executable="/usr/local/bin/litra"):
        self.executable = executable
        self.lock = asyncio.Lock()

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
            devices = json.loads(await self._run("devices", "--json"))
            beams = [d for d in devices if d["device_type"] == "beam"]
            if not beams:
                raise RuntimeError("No accessible Litra Beam found")
            for device in beams:
                target = ("--device-path", device["device_path"])
                minimum = device["minimum_brightness_in_lumen"]
                maximum = device["maximum_brightness_in_lumen"]
                if not device["is_on"]:
                    if increase:
                        await self._run("brightness", *target, "--value", str(minimum))
                        await self._run("on", *target)
                    continue
                # Five percentage points of the device's maximum output.
                step = max(1, round(maximum * 0.05))
                value = device["brightness_in_lumen"] + (step if increase else -step)
                if value < minimum:
                    await self._run("off", *target)
                else:
                    await self._run("brightness", *target, "--value", str(min(value, maximum)))
