import time
import uuid
from pathlib import Path

from sqlalchemy import JSON, Column, Float, MetaData, String, Table, create_engine, event, select

metadata = MetaData()
jobs = Table(
    "jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("kind", String, nullable=False),
    Column("state", String, nullable=False),
    Column("source", String, nullable=False),
    Column("preset", String, nullable=False),
    Column("title", String, nullable=False),
    Column("message", String, nullable=False),
    Column("error_code", String),
    Column("details", JSON),
    Column("progress", JSON),
    Column("artifact", String),
    Column("sha256", String),
    Column("created", Float),
    Column("updated", Float),
)


class Store:
    def __init__(self, directory: Path):
        self.deliveries = {}
        self.engine = create_engine(f"sqlite:///{directory / 'queue.sqlite3'}")

        @event.listens_for(self.engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")

        # Initial test schema. Alembic migrations are required before schema v2.
        metadata.create_all(self.engine)

    def all(self):
        with self.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(jobs).order_by(jobs.c.created.desc())
                ).mappings()
            ]

    def get(self, job_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
            return dict(row) if row else None

    def visible(self):
        return [job for job in self.all() if not (job.get("details") or {}).get("_queue_hidden")]

    def dismiss(self, job_id):
        job = self.get(job_id)
        details = {**(job.get("details") or {}), "_queue_hidden": True}
        # Hiding from the queue must not restart the file's retention clock.
        with self.engine.begin() as connection:
            connection.execute(jobs.update().where(jobs.c.id == job_id).values(details=details))

    def patch_details(self, job_id, changes):
        # Enrichment must not alter completion time or extend retention.
        job = self.get(job_id)
        with self.engine.begin() as connection:
            connection.execute(
                jobs.update()
                .where(jobs.c.id == job_id)
                .values(details={**(job.get("details") or {}), **changes})
            )

    def create(self, kind, source, preset="720", *, replace=None, prepare=None):
        job_id = uuid.uuid4().hex
        initial = {
            "title": "Получение метаданных" if kind == "probe" else "Загрузка медиа",
        }
        if prepare:
            initial.update(prepare(job_id))
        with self.engine.begin() as connection:
            if replace:
                details = {**(replace.get("details") or {}), "_queue_hidden": True}
                connection.execute(
                    jobs.update().where(jobs.c.id == replace["id"]).values(details=details)
                )
            connection.execute(
                jobs.insert().values(
                    id=job_id,
                    kind=kind,
                    source=source,
                    preset=preset,
                    state="queued",
                    **initial,
                    message="В очереди",
                    created=time.time(),
                    updated=time.time(),
                )
            )
        return self.get(job_id)

    def update(self, job_id, **values):
        with self.engine.begin() as connection:
            connection.execute(
                jobs.update().where(jobs.c.id == job_id).values(**values, updated=time.time())
            )


def public_job(job):
    result = {key: value for key, value in job.items() if key not in {"source", "artifact"}}
    if result.get("details"):
        result["details"] = {
            key: value for key, value in result["details"].items() if key != "_queue_hidden"
        }
    return result
