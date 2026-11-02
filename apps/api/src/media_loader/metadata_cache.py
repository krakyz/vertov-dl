"""Short-lived, success-only metadata cache with request and cookie generations."""

import time


class MetadataCache:
    def __init__(self, ttl=300):
        self.ttl = ttl
        self.generation = 0
        self.sequence = 0
        self.latest = {}
        self.tickets = {}
        self.entries = {}

    def invalidate(self):
        self.generation += 1
        self.latest.clear()
        self.tickets.clear()
        self.entries.clear()

    def begin(self, job):
        self.sequence += 1
        ticket = (self.generation, self.sequence)
        self.latest[job["source"]] = ticket
        self.tickets[job["id"]] = ticket
        self.entries.pop(job["source"], None)
        while len(self.tickets) > 2000:
            self.tickets.pop(next(iter(self.tickets)))
        while len(self.latest) > 2000:
            source = next(iter(self.latest))
            self.latest.pop(source)
            self.entries.pop(source, None)

    def put(self, job):
        ticket = self.tickets.get(job["id"])
        if (
            job["kind"] != "probe"
            or job["state"] != "completed"
            or not (job.get("details") or {}).get("title")
        ):
            return
        if not ticket or self.latest.get(job["source"]) != ticket:
            return
        self.entries[job["source"]] = (job["id"], time.monotonic() + self.ttl)
        if len(self.entries) > 1000:
            self.entries.pop(next(iter(self.entries)))

    def get(self, source, store):
        cached = self.entries.get(source)
        if not cached or cached[1] <= time.monotonic():
            self.entries.pop(source, None)
            return None
        job = store.get(cached[0])
        if not job or job["state"] != "completed":
            self.entries.pop(source, None)
            return None
        return job
