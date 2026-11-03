import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest
from media_loader import manager as module
from media_loader.config import Settings
from media_loader.manager import Manager
from media_loader.store import Store


async def test_cancel_terminates_real_child_and_cleans_files(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path, reserve_bytes=0, auth_token="test-only-token-123456789012345"
    )
    store = Store(tmp_path)
    job = store.create("download", "https://example.org/test")
    child = tmp_path / "child.py"
    child.write_text(
        "import json,pathlib,sys,time\n"
        "spec=json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        "(pathlib.Path(spec['directory'])/'media.part').write_bytes(b'partial')\n"
        "print(json.dumps({'event':'phase','state':'downloading'}),flush=True)\n"
        "time.sleep(120)\n"
    )
    original = asyncio.create_subprocess_exec
    children = []

    async def spawn(*args, **kwargs):
        if len(args) > 2 and args[1:3] == ("-m", "media_loader.task"):
            process = await original(sys.executable, str(child), *args[3:], **kwargs)
            children.append(process)
            return process
        return await original(*args, **kwargs)

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(Manager(settings, store, 1).execute(job))
    for _ in range(100):
        if store.get(job["id"])["state"] == "downloading":
            break
        await asyncio.sleep(0.05)
    assert store.get(job["id"])["state"] == "downloading"
    store.update(job["id"], state="cancelled")
    await asyncio.wait_for(task, 10)
    assert children[0].returncode is not None
    assert not (tmp_path / "jobs" / job["id"]).exists()
    assert store.get(job["id"])["state"] == "cancelled"


async def test_worker_cannot_connect_directly_to_lan():
    code = """
import socket
from media_loader.task import restrict_python_network
restrict_python_network('socks5h://127.0.0.1:40000')
try:
    socket.socket().connect(('127.0.0.1', 80))
except OSError as e:
    print(str(e))
else:
    raise SystemExit(1)
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", code, stdout=asyncio.subprocess.PIPE
    )
    output, _ = await process.communicate()
    assert process.returncode == 0
    assert b"Direct network access blocked" in output


async def test_probe_ready_before_preview_and_preview_failure_keeps_success(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path, reserve_bytes=0, auth_token="test-only-token-123456789012345"
    )
    store = Store(tmp_path)
    job = store.create("probe", "https://example.org/synthetic")
    child = tmp_path / "preview_worker.py"
    child.write_text(
        "import json,time\nprint(json.dumps({'event':'metadata','details':{'title':'Ready','formats':[],'has_thumbnail':False}}),flush=True)\ntime.sleep(120)\n"
    )
    original = asyncio.create_subprocess_exec
    processes = []

    async def spawn(*args, **kwargs):
        process = await original(sys.executable, str(child), **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    manager = Manager(settings, store, 1)
    task = asyncio.create_task(manager.execute(job))
    try:
        for _ in range(100):
            if store.get(job["id"])["state"] == "completed":
                break
            await asyncio.sleep(0.02)
        assert store.get(job["id"])["state"] == "completed"
        assert not task.done()
        processes[0].kill()
        await asyncio.wait_for(task, 10)
        assert store.get(job["id"])["state"] == "completed"
        assert store.get(job["id"])["title"] == "Ready"
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        store.engine.dispose()


async def test_preparation_failure_does_not_stop_queue(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path, reserve_bytes=0, auth_token="test-only-token-123456789012345"
    )
    store = Store(tmp_path)
    first = store.create("download", "https://example.org/first")
    second = store.create("download", "https://example.org/second")
    folder = tmp_path / "jobs"
    folder.mkdir()
    (folder / first["id"]).touch()
    manager = Manager(settings, store, 1)
    execute = manager.execute

    async def run_job(job):
        if job["id"] == first["id"]:
            await execute(job)
        else:
            store.update(job["id"], state="completed")
            manager.stopping = True

    monkeypatch.setattr(manager, "execute", run_job)
    await asyncio.wait_for(manager.run(), 5)
    assert store.get(first["id"])["state"] == "failed"
    assert store.get(second["id"])["state"] == "completed"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process groups")
@pytest.mark.parametrize("leader_exits", [False, True])
async def test_stop_process_kills_descendant_ignoring_term(tmp_path, leader_exits):
    marker = tmp_path / "pid"
    child = (
        "import os,signal,time,pathlib;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(60)"
    )
    parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);"
    if not leader_exits:
        parent += "time.sleep(60)"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", parent, start_new_session=True
    )
    try:
        for _ in range(100):
            if marker.exists() and marker.read_text():
                break
            await asyncio.sleep(0.02)
        pid = int(marker.read_text())
        if leader_exits:
            await asyncio.wait_for(process.wait(), 2)
        await asyncio.wait_for(module.stop_process(process), 4)
        status = Path("/proc") / str(pid) / "status"
        for _ in range(20):
            try:
                lines = status.read_text().splitlines()
                if any(line.startswith("State:") and "Z (zombie)" in line for line in lines):
                    break
            except FileNotFoundError:
                break
            await asyncio.sleep(0.025)
        else:
            pytest.fail("Worker descendant is still running")
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
