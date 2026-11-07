"""Tap for Litra; hold for repeated office light steps, without queuing steps."""

import asyncio


class LightKeyPresses:
    def __init__(self, dispatch, hold_seconds=0.7, repeat_seconds=0.3):
        self.dispatch = dispatch
        self.hold_seconds = hold_seconds
        self.repeat_seconds = repeat_seconds
        self.pending = {}
        self.tasks = set()

    def _task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def press(self, key, action):
        if key in self.pending:
            return
        press = {"action": action, "held": False}
        self.pending[key] = press
        press["task"] = self._task(self._hold(press))

    async def _hold(self, press):
        await asyncio.sleep(self.hold_seconds)
        press["held"] = True
        while True:
            await self.dispatch("office_" + press["action"])
            await asyncio.sleep(self.repeat_seconds)

    def release(self, key):
        press = self.pending.pop(key, None)
        if press is not None:
            press["task"].cancel()
            if not press["held"]:
                self._task(self.dispatch(press["action"]))

    def cancel(self):
        for press in self.pending.values():
            press["task"].cancel()
        self.pending.clear()

    async def close(self):
        self.cancel()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
