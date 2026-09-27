"""后台任务执行器：生产环境异步执行，测试环境同步执行"""
import asyncio


class BackgroundRunner:
    def __init__(self, sync: bool = False):
        self.sync = sync
        self.tasks: list[asyncio.Task] = []

    async def run(self, coro):
        if self.sync:
            await coro
            return None
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        task.add_done_callback(self._discard)
        return task

    def _discard(self, task):
        try:
            self.tasks.remove(task)
        except ValueError:
            pass
        if not task.cancelled() and task.exception() is not None:
            import logging
            logging.getLogger("sip").error("后台任务异常: %s", task.exception())
