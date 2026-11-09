"""Bounded process-local weighted dispatch; durable admission is the fleet ceiling."""

import asyncio
from collections import OrderedDict, deque

from canvas_bridge.usage.ledger import deny


class FairQueue:
    schedule = ("interactive",) * 5 + ("scheduled_sync",) * 2 + ("exploratory",)

    def __init__(self, capacity=8, maximum=64):
        self.capacity, self.maximum = capacity, maximum
        self.pending = {kind: OrderedDict() for kind in set(self.schedule)}
        self.active, self.owners, self.position = 0, set(), 0

    async def acquire(self, owner, workload):
        if sum(len(q) for group in self.pending.values() for q in group.values()) >= self.maximum:
            deny("LOCAL_REQUEST_BUSY")
        future = asyncio.get_running_loop().create_future()
        self.pending[workload].setdefault(owner, deque()).append(future)
        self.dispatch()
        try:
            async with asyncio.timeout(3):
                await future
            return Ticket(self, owner)
        except BaseException:
            queue = self.pending[workload].get(owner)
            if queue and future in queue:
                queue.remove(future)
                if not queue:
                    self.pending[workload].pop(owner, None)
            elif future.done() and not future.cancelled():
                self.release(owner)
            self.dispatch()
            raise

    def dispatch(self):
        while self.active < self.capacity:
            selected = None
            for _ in self.schedule:
                kind = self.schedule[self.position]
                self.position = (self.position + 1) % len(self.schedule)
                group = self.pending[kind]
                for owner in list(group):
                    queue = group[owner]
                    while queue and queue[0].cancelled():
                        queue.popleft()
                    if not queue:
                        del group[owner]
                    elif owner not in self.owners:
                        future = queue.popleft()
                        if queue:
                            group.move_to_end(owner)
                        else:
                            del group[owner]
                        selected = owner, future
                        break
                if selected:
                    break
            if not selected:
                return
            owner, future = selected
            self.active += 1
            self.owners.add(owner)
            future.set_result(None)

    def release(self, owner):
        if owner in self.owners:
            self.owners.remove(owner)
            self.active -= 1
        self.dispatch()


class Ticket:
    def __init__(self, queue, owner):
        self.queue, self.owner, self.closed = queue, owner, False

    def close(self):
        if not self.closed:
            self.closed = True
            self.queue.release(self.owner)
