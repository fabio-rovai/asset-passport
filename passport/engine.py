"""Drive the Open Ontologies engine over MCP stdio, and keep a transcript.

Nothing here judges an item. Every verdict is read off what the engine and the
Lean checkers returned; this module only sequences the calls and records them,
so the page can print the transcript instead of a summary somebody typed.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import math
import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GA = "https://tesseractsemantics.com/ns/asset-passport/ga#"

TOOLS = [
    "onto_clear", "onto_load", "onto_ingest", "onto_reason", "onto_query",
    "onto_shacl", "onto_pack", "onto_unpack",
]


def engine_binary() -> str:
    """$OO_BIN, else the sibling open-ontologies checkout's release build."""
    explicit = os.environ.get("OO_BIN")
    if explicit:
        return explicit
    sibling = ROOT.parent / "open-ontologies" / "target" / "release" / "open-ontologies"
    if sibling.exists():
        return str(sibling)
    return "open-ontologies"


class EngineError(RuntimeError):
    pass


class ConfigError(EngineError):
    """A setting or a games root that is wrong. The run failed before anything
    was judged, so the command line reports it as a failed run, not as a
    verdict (it subclasses EngineError so that every caller that stops on an
    engine failure stops on this too)."""


class EngineTimeout(EngineError):
    """The engine did not answer within the deadline, so the run was stopped."""

    def __init__(self, message: str, timeout: float):
        super().__init__(message)
        self.timeout = timeout


DEFAULT_TIMEOUT = 60.0
# A day. selectors.select raises TypeError for a timeout above about 1e9 s on
# macOS, so a large but finite value used to pass the check below and then
# break every engine start with a message that did not name the variable.
MAX_TIMEOUT = 86_400.0
TIMEOUT_ENV = "ASSET_PASSPORT_ENGINE_TIMEOUT"
RUN_TIMEOUT_ENV = "ASSET_PASSPORT_RUN_TIMEOUT"


def _seconds(var: str, default: float | None) -> float | None:
    raw = os.environ.get(var)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not (0 < value <= MAX_TIMEOUT):
        raise ConfigError(f"{var} must be a positive number of seconds, at most {MAX_TIMEOUT:g}, not {raw!r}")
    return value


def reply_timeout() -> float:
    """Seconds the engine has to answer one request, and a Lean checker has to
    finish one run: $ASSET_PASSPORT_ENGINE_TIMEOUT, else 60. A value that is not
    a positive number of seconds up to a day is a failed run, not a deadline
    that silently never fires."""
    return _seconds(TIMEOUT_ENV, DEFAULT_TIMEOUT)


# The deadline of the whole run in progress: (monotonic deadline, its length).
# One live request starts several engine processes and makes about fifteen
# calls, so a limit on each reply alone let a slow engine keep a request past
# the platform's own limit while every single reply stayed under it.
_RUN_DEADLINE: contextvars.ContextVar = contextvars.ContextVar("asset_passport_run_deadline", default=None)


@contextlib.contextmanager
def run_deadline(seconds: float | None = None):
    """One deadline for everything inside the block: every engine start, every
    request and every Lean checker run. `seconds` defaults to
    $ASSET_PASSPORT_RUN_TIMEOUT; with neither, the block has no overall limit
    and only the limit on each reply applies. A block inside another keeps the
    earlier of the two deadlines."""
    if seconds is None:
        seconds = _seconds(RUN_TIMEOUT_ENV, None)
    outer = _RUN_DEADLINE.get()
    mine = None if seconds is None else (time.monotonic() + seconds, seconds)
    if mine is None or (outer is not None and outer[0] <= mine[0]):
        yield outer
        return
    token = _RUN_DEADLINE.set(mine)
    try:
        yield mine
    finally:
        _RUN_DEADLINE.reset(token)


def wait_limit() -> tuple[float, float, str]:
    """How long the next wait may take: (seconds left, the limit that sets it,
    the words that name that limit). The limit on one reply, or what is left of
    the run's deadline when that is sooner."""
    per = reply_timeout()
    run = _RUN_DEADLINE.get()
    if run is not None:
        left = run[0] - time.monotonic()
        if left < per:
            return left, run[1], f"within the {run[1]:g} s the whole run may take (the limit {RUN_TIMEOUT_ENV} sets)"
    return per, per, f"within {per:g} s (the limit {TIMEOUT_ENV} sets)"


def kill_group(proc: subprocess.Popen) -> None:
    """SIGKILL a process started with start_new_session=True and everything it
    started. Killing the engine alone left a hung oo-cert or oo-shacl it had
    started running for ever, adopted by PID 1."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass


def run_bounded(cmd: list[str]) -> tuple[int, str, str]:
    """Run a checker to completion under the same deadline as an engine reply
    (wait_limit), in its own process group, and kill the group if it overruns.
    Returns (exit code, stdout, stderr); raises subprocess.TimeoutExpired, with
    the words naming the limit as its output, when the deadline passes."""
    left, _, words = wait_limit()
    if left <= 0:
        raise subprocess.TimeoutExpired(cmd, 0, output=words)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    try:
        out, err = p.communicate(timeout=left)
    except subprocess.TimeoutExpired:
        kill_group(p)
        p.communicate()
        raise subprocess.TimeoutExpired(cmd, left, output=words) from None
    except BaseException:
        kill_group(p)
        p.wait()
        raise
    return p.returncode, out, err


class Engine:
    """One engine process, one in-memory store, one transcript."""

    def __init__(self, workdir: Path, binary: str | None = None, timeout: float | None = None):
        self.timeout = timeout  # None: reply_timeout() and the run's deadline, read at each request
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        data_dir = self.workdir / "oo-data"
        data_dir.mkdir(exist_ok=True)
        # A config of its own, so a run never writes into ~/.open-ontologies:
        # the compile cache is off and its directory, if read, is the run's.
        (data_dir / "config.toml").write_text(
            f'[cache]\nenabled = false\ndir = "{data_dir / "cache"}"\n'
            # No embedding model: nothing here asks for similarity, and a
            # release that loads one at startup spends seconds on it.
            f'[embeddings]\nmodel_path = "{data_dir / "no-model.onnx"}"\n'
            f'tokenizer_path = "{data_dir / "no-tokenizer.json"}"\n'
        )
        self.binary = binary or engine_binary()
        self.transcript: list[dict] = []
        self._id = 0
        env = os.environ.copy()
        lean_bin = ROOT.parent / "open-ontologies" / "lean" / ".lake" / "build" / "bin"
        for var, name in (("OO_CERT", "oo-cert"), ("OO_SHACL", "oo-shacl")):
            if var not in env and (lean_bin / name).exists():
                env[var] = str(lean_bin / name)
        self.proc = subprocess.Popen(
            [
                self.binary, "serve",
                "--data-dir", str(data_dir),
                "--config", str(data_dir / "config.toml"),
                "--idle-ttl-secs", "0",
                "--tools-allow", ",".join(TOOLS),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            bufsize=0,
            # Its own process group, so stopping it also stops the checkers
            # (oo-cert, oo-shacl) it starts (kill_group).
            start_new_session=True,
        )
        assert self.proc.stdin is not None
        # Writes wait with a deadline too (_send): a blocking write to an engine
        # that stopped reading waited for ever once a message filled the pipe.
        os.set_blocking(self.proc.stdin.fileno(), False)
        self._buf = b""
        try:
            init = self._rpc("initialize", {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "asset-passport", "version": "0.1.0"},
            })
            self.server_info = init.get("serverInfo", {})
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            listed = self._rpc("tools/list", {})
            self.schemas = {t["name"]: t.get("inputSchema", {}) for t in listed.get("tools", [])}
        except BaseException:
            self._kill()  # a process that never finished starting is not left behind
            raise

    # ------------------------------------------------------------- transport

    def _limit(self) -> tuple[float, float, str]:
        if self.timeout is not None:
            return self.timeout, self.timeout, f"within {self.timeout:g} s (the limit {TIMEOUT_ENV} sets)"
        return wait_limit()

    def _timed_out(self, method: str, limit: float, words: str) -> EngineTimeout:
        self._kill()
        return EngineTimeout(f"the engine did not answer {method} {words}, so the run was stopped", limit)

    def _send(self, msg: dict, method: str | None = None, deadline: tuple | None = None) -> None:
        """Write one message, waiting at most until the deadline for the engine
        to read it."""
        assert self.proc.stdin is not None
        method = method or msg.get("method", "a message")
        if deadline is None:
            left, limit, words = self._limit()
            deadline = (time.monotonic() + left, limit, words)
        when, limit, words = deadline
        view = memoryview((json.dumps(msg) + "\n").encode())
        fd = self.proc.stdin.fileno()
        with selectors.DefaultSelector() as sel:
            sel.register(fd, selectors.EVENT_WRITE)
            while view:
                try:
                    view = view[os.write(fd, view):]
                    continue
                except BlockingIOError:
                    pass
                except OSError as err:  # BrokenPipeError among them
                    raise EngineError(f"the engine stopped reading its input ({type(err).__name__})") from err
                left = when - time.monotonic()
                if left <= 0 or not sel.select(left):
                    raise self._timed_out(method, limit, words)

    def _readline(self, method: str, deadline: tuple) -> bytes:
        """One line of the engine's output, or EngineTimeout once the deadline
        passes. A blocking readline waited for ever on an engine that hung, and
        with it the CLI, the build and a serverless worker."""
        assert self.proc.stdout is not None
        when, limit, words = deadline
        fd = self.proc.stdout.fileno()
        with selectors.DefaultSelector() as sel:
            sel.register(fd, selectors.EVENT_READ)
            while b"\n" not in self._buf:
                left = when - time.monotonic()
                if left <= 0 or not sel.select(left):
                    raise self._timed_out(method, limit, words)
                chunk = os.read(fd, 65536)
                if not chunk:
                    raise EngineError(f"engine closed the pipe during {method}")
                self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        want = self._id
        left, limit, words = self._limit()
        deadline = (time.monotonic() + left, limit, words)
        self._send({"jsonrpc": "2.0", "id": want, "method": method, "params": params}, method, deadline)
        while True:
            line = self._readline(method, deadline)
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except ValueError as err:
                raise EngineError(f"the engine wrote a line that is not JSON during {method}") from err
            if msg.get("id") != want:
                continue  # a notification, or a reply to nobody
            if "error" in msg:
                raise EngineError(f"{method}: {msg['error']}")
            return msg["result"]

    def accepts(self, tool: str, arg: str) -> bool:
        """Does this build's tool take this argument? Read off its own schema."""
        return arg in self.schemas.get(tool, {}).get("properties", {})

    def call(self, tool: str, **args) -> dict:
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content", []))
        try:
            out = json.loads(text)
        except json.JSONDecodeError:
            out = {"raw": text}
        if res.get("isError"):
            out = {"error": out}
        self.transcript.append({"tool": tool, "args": self._shown(args), "result": out})
        return out

    def load(self, path: Path) -> dict:
        """ADD a file to the store. onto_load with a path goes through the
        registry, which clears the store first (one active ontology per slot);
        inline Turtle bypasses the registry and accumulates."""
        res = self._rpc("tools/call", {"name": "onto_load",
                                       "arguments": {"turtle": Path(path).read_text()}})
        text = "".join(c.get("text", "") for c in res.get("content", []))
        try:
            out = json.loads(text)
        except json.JSONDecodeError:
            out = {"raw": text}
        if res.get("isError"):
            out = {"error": out}
        self.transcript.append({"tool": "onto_load",
                                "args": {"turtle": "<contents of " + self._shown({"p": str(path)})["p"] + ">"},
                                "result": out})
        return out

    def _shown(self, args: dict) -> dict:
        """Paths relative to the repo or the run, so a transcript is portable."""
        shown = {}
        for k, v in args.items():
            if isinstance(v, str) and v.startswith(str(self.workdir)):
                v = "<run>/" + os.path.relpath(v, self.workdir)
            elif isinstance(v, str) and v.startswith(str(ROOT)):
                v = os.path.relpath(v, ROOT)
            shown[k] = v
        return shown

    def _kill(self) -> None:
        """Stop the process and every process it started, and wait for it, so
        nothing any of them does afterwards can write into a run directory that
        is about to be removed."""
        kill_group(self.proc)
        self.proc.wait()
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                if pipe is not None:
                    pipe.close()
            except OSError:
                pass

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()  # type: ignore[union-attr]
            except OSError:
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        self._kill()

    def __enter__(self) -> "Engine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def scratch(prefix: str) -> Path:
    """A new directory for one run. The caller removes it (see scratch_dir)."""
    return Path(tempfile.mkdtemp(prefix=f"asset-passport-{prefix}-"))


@contextlib.contextmanager
def scratch_dir(prefix: str):
    """A scratch directory that is removed when the block ends, however it ends."""
    d = scratch(prefix)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)
