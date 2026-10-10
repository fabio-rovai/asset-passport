"""Drive the Open Ontologies engine over MCP stdio, and keep a transcript.

Nothing here judges an item. Every verdict is read off what the engine and the
Lean checkers returned; this module only sequences the calls and records them,
so the page can print the transcript instead of a summary somebody typed.
"""

from __future__ import annotations

import contextlib
import json
import os
import selectors
import shutil
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


class EngineTimeout(EngineError):
    """The engine did not answer within the deadline, so the run was stopped."""

    def __init__(self, message: str, timeout: float):
        super().__init__(message)
        self.timeout = timeout


DEFAULT_TIMEOUT = 60.0
TIMEOUT_ENV = "ASSET_PASSPORT_ENGINE_TIMEOUT"


def reply_timeout() -> float:
    """Seconds the engine has to answer one request: $ASSET_PASSPORT_ENGINE_TIMEOUT,
    else 60. A value that is not a positive number is a failed run, not a
    deadline that silently never fires."""
    raw = os.environ.get(TIMEOUT_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not (value > 0 and value != float("inf")):
        raise EngineError(f"{TIMEOUT_ENV} must be a positive number of seconds, not {raw!r}")
    return value


class Engine:
    """One engine process, one in-memory store, one transcript."""

    def __init__(self, workdir: Path, binary: str | None = None, timeout: float | None = None):
        self.timeout = reply_timeout() if timeout is None else timeout
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
        )
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

    def _send(self, msg: dict) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        except (BrokenPipeError, OSError) as err:
            raise EngineError(f"the engine stopped reading its input ({type(err).__name__})") from err

    def _readline(self, method: str, deadline: float) -> bytes:
        """One line of the engine's output, or EngineTimeout once the deadline
        passes. A blocking readline waited for ever on an engine that hung, and
        with it the CLI, the build and a serverless worker."""
        assert self.proc.stdout is not None
        fd = self.proc.stdout.fileno()
        with selectors.DefaultSelector() as sel:
            sel.register(fd, selectors.EVENT_READ)
            while b"\n" not in self._buf:
                left = deadline - time.monotonic()
                if left <= 0 or not sel.select(left):
                    self._kill()
                    raise EngineTimeout(
                        f"the engine did not answer {method} within {self.timeout:g} s "
                        f"(the limit {TIMEOUT_ENV} sets), so the run was stopped", self.timeout)
                chunk = os.read(fd, 65536)
                if not chunk:
                    raise EngineError(f"engine closed the pipe during {method}")
                self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        want = self._id
        self._send({"jsonrpc": "2.0", "id": want, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
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
        """Stop the process and wait for it, so nothing it does afterwards can
        write into a run directory that is about to be removed."""
        if self.proc.poll() is None:
            self.proc.kill()
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
