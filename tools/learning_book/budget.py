"""累计账本与独立在途监控；停止仅针对明确绑定的单进程实例。"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import threading
import time

from .contracts import DeliveryError, digest, identifier, read_json


def owns_listener(pid: int, port: int) -> bool:
    """通过 OS 只读表核验实际 server PID 拥有指定 loopback 监听端口。"""
    if os.name != "nt":
        try:
            sockets = {p.readlink().as_posix() for p in (Path("/proc") / str(pid) / "fd").iterdir()}
            for name in ("tcp", "tcp6"):
                for line in (Path("/proc/net") / name).read_text().splitlines()[1:]:
                    fields = line.split()
                    if (fields[3] == "0A" and int(fields[1].split(":")[1], 16) == port
                            and "socket:[" + fields[9] + "]" in sockets):
                        return True
        except (OSError, IndexError, ValueError):
            return False
        return False
    from ctypes import wintypes as w
    class Row4(ctypes.Structure):
        _fields_ = [(name, w.DWORD) for name in ("state", "localAddress", "localPort", "remoteAddress", "remotePort", "pid")]
    class Row6(ctypes.Structure):
        _fields_ = [("localAddress", ctypes.c_ubyte * 16), ("localScope", w.DWORD), ("localPort", w.DWORD),
                    ("remoteAddress", ctypes.c_ubyte * 16), ("remoteScope", w.DWORD),
                    ("remotePort", w.DWORD), ("state", w.DWORD), ("pid", w.DWORD)]
    ip = ctypes.WinDLL("iphlpapi", use_last_error=True)
    ip.GetExtendedTcpTable.argtypes = (ctypes.c_void_p, ctypes.POINTER(w.ULONG), w.BOOL, w.ULONG, w.ULONG, w.ULONG)
    for family, row_type in ((2, Row4), (23, Row6)):
        size = w.ULONG(0)
        if ip.GetExtendedTcpTable(None, ctypes.byref(size), False, family, 3, 0) not in (0, 122):
            continue
        buffer = ctypes.create_string_buffer(size.value)
        if ip.GetExtendedTcpTable(buffer, ctypes.byref(size), False, family, 3, 0) != 0:
            continue
        count = w.DWORD.from_buffer_copy(buffer.raw[:4]).value
        for index in range(count):
            row = row_type.from_buffer_copy(buffer.raw, 4 + index * ctypes.sizeof(row_type))
            if row.pid == pid and socket.ntohs(row.localPort & 0xFFFF) == port:
                if family == 2 and row.localAddress not in (0, 0x0100007F):
                    continue
                if family == 23 and bytes(row.localAddress) not in (bytes(16), bytes(15) + b"\x01"):
                    continue
                return True
    return False


def _win_handle(pid, access):
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    handle = kernel.OpenProcess(access, False, pid)
    if not handle:
        raise DeliveryError("process_missing", "无法打开指定实例进程", "failed")
    return kernel, handle


def _win_info(kernel, handle):
    from ctypes import wintypes as w
    creation, exit_time, system, user = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
    kernel.GetProcessTimes.argtypes = (w.HANDLE,) + (ctypes.POINTER(w.FILETIME),) * 4
    if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                                  ctypes.byref(system), ctypes.byref(user)):
        raise DeliveryError("process_identity", "无法核对进程创建时间", "failed")
    size = w.DWORD(32768)
    path = ctypes.create_unicode_buffer(size.value)
    kernel.QueryFullProcessImageNameW.argtypes = (w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD))
    if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
        raise DeliveryError("process_identity", "无法核对进程可执行文件", "failed")
    return {"executable": str(Path(path.value).resolve()),
            "startedToken": str((creation.dwHighDateTime << 32) | creation.dwLowDateTime)}


def _children(pid):
    if os.name != "nt":
        result = []
        for path in Path("/proc").glob("[0-9]*/stat"):
            try:
                data = path.read_text().rsplit(")", 1)[1].split()
                if int(data[1]) == pid:
                    result.append(int(path.parent.name))
            except (OSError, ValueError, IndexError):
                continue
        return result
    from ctypes import wintypes as w
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD),
                    ("cntThreads", w.DWORD), ("th32ParentProcessID", w.DWORD),
                    ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD), ("szExeFile", w.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (w.DWORD, w.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = (w.HANDLE, ctypes.POINTER(Entry))
    kernel.Process32NextW.argtypes = (w.HANDLE, ctypes.POINTER(Entry))
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise DeliveryError("process_tree", "无法核对实例子进程", "failed")
    try:
        entry, result = Entry(), []
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.th32ParentProcessID == pid:
                result.append(entry.th32ProcessID)
            ok = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return result
    finally:
        kernel.CloseHandle(snapshot)


def process_identity(pid: int) -> dict:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise DeliveryError("process_id", "processId 必须是正整数")
    if os.name == "nt":
        kernel, handle = _win_handle(pid, 0x1000)
        try:
            info = _win_info(kernel, handle)
        finally:
            kernel.CloseHandle(handle)
    else:
        try:
            proc = Path("/proc") / str(pid)
            info = {"executable": str((proc / "exe").resolve(strict=True)),
                    "startedToken": (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]}
        except (OSError, IndexError) as exc:
            raise DeliveryError("process_missing", "无法核对指定实例", "failed") from exc
    return {"processId": pid, **info, "children": _children(pid)}


class ProcessStop:
    """只支持实际 server 的单进程 PID；拒绝 launcher/worker 树而不盲杀。"""
    def __init__(self, receipt: dict):
        self.receipt = receipt
        self.port = None

    def bind_endpoint(self, base_url: str):
        from urllib.parse import urlsplit
        self.port = urlsplit(base_url).port or 80

    def verify(self):
        pid = self.receipt.get("processId")
        if pid == os.getpid():
            raise DeliveryError("process_self", "不能将控制器自身作为停止目标")
        info = process_identity(pid)
        for child in info["children"]:
            child_info = process_identity(child)
            console = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "conhost.exe"
            if (os.name != "nt" or Path(child_info["executable"]) != console.resolve()
                    or not 0 <= int(child_info["startedToken"]) - int(info["startedToken"]) <= 100_000_000
                    or child_info["children"]):
                raise DeliveryError("process_mismatch", "实例存在未管理子进程；拒绝停止", "failed")
        if any(info[k] != self.receipt.get(k)
               for k in ("executable", "startedToken")):
            raise DeliveryError("process_mismatch", "停止目标身份不符或存在未管理子进程", "failed")
        if self.receipt.get("ownership") != "dedicated_single_worker":
            raise DeliveryError("process_ownership", "需明确绑定独占单 worker 的实际 server PID")
        if self.port is not None and not owns_listener(pid, self.port):
            raise DeliveryError("process_endpoint", "指定进程未拥有目标服务监听端口", "failed")
        return info

    def __call__(self):
        info = self.verify()
        pid = info["processId"]
        if os.name == "nt":
            from ctypes import wintypes as w
            kernel, handle = _win_handle(pid, 0x1000 | 0x0001 | 0x00100000)
            try:
                # 再在用于终止的同一 handle 核验，防止 PID 被回收重用。
                if _win_info(kernel, handle) != {k: info[k] for k in ("executable", "startedToken")}:
                    raise DeliveryError("process_reused", "停止时实例身份发生变化", "failed")
                kernel.TerminateProcess.argtypes = (w.HANDLE, w.UINT)
                kernel.WaitForSingleObject.argtypes = (w.HANDLE, w.DWORD)
                if not kernel.TerminateProcess(handle, 1) or kernel.WaitForSingleObject(handle, 5000) != 0:
                    raise DeliveryError("stop_failed", "未能确认指定实例停止", "failed")
            finally:
                kernel.CloseHandle(handle)
        else:
            # Linux pidfd 在句柄上定位实例，避免普通 os.kill 的 PID 重用竞态。
            if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
                raise DeliveryError("stop_unsupported", "此平台缺少安全实例停止接口", "failed")
            handle = os.pidfd_open(pid)
            try:
                self.verify()
                signal.pidfd_send_signal(handle, signal.SIGTERM)
                import select
                if not select.select([handle], [], [], 5)[0]:
                    raise DeliveryError("stop_failed", "实例停止未确认", "failed")
            finally:
                os.close(handle)


class Budget:
    def __init__(self, context: dict, scope: dict, *, stop=None):
        if not isinstance(context, dict) or set(context) - {"schemaVersion", "contextId", "scope", "ledger",
                "baselineCallIds", "pauseAt", "limit", "pollSeconds", "maxSilentSeconds", "stopProcess", "localEmbedding"}:
            raise DeliveryError("budget_fields", "预算上下文字段无效")
        self.context = context
        identifier(context.get("contextId"), "contextId")
        if context.get("scope") != scope:
            raise DeliveryError("budget_scope", "预算上下文与目标部署／用户／workspace 不符")
        pause, limit = context.get("pauseAt"), context.get("limit")
        if (type(pause) is not int or type(limit) is not int or not 0 < pause <= limit):
            raise DeliveryError("budget_threshold", "预算必须有正整数暂停线和有限总额度")
        baseline = context.get("baselineCallIds")
        if not isinstance(baseline, list) or any(not isinstance(x, str) for x in baseline) or len(set(baseline)) != len(baseline):
            raise DeliveryError("budget_baseline", "baselineCallIds 必须是去重的 call_id 列表")
        self.ledger = Path(context.get("ledger", "")).resolve()
        self.baseline = set(baseline)
        self.interval = float(context.get("pollSeconds", 1))
        self.silent = float(context.get("maxSilentSeconds", 120))
        if not 0.02 <= self.interval <= 10 or not self.interval <= self.silent <= 3600:
            raise DeliveryError("budget_interval", "无效监控周期")
        if stop is None and not isinstance(context.get("stopProcess", {}), dict):
            raise DeliveryError("stop_control", "stopProcess 必须是实例控制对象")
        self.stop_control = stop if stop is not None else ProcessStop(context.get("stopProcess", {}))
        self.blocked = threading.Event()
        self.events = []
        self.running = False
        self.floor = {}
        self._event_lock = threading.Lock()

    def _position_from_rows(self, rows) -> dict:
        try:
            total = reported = estimated = missing = 0
            call_ids, counted = set(), {}
            for call_id, raw in rows:
                if not isinstance(call_id, str) or call_id in call_ids:
                    raise ValueError("call identity")
                call_ids.add(call_id)
                if call_id in self.baseline:
                    continue
                usage = json.loads(raw)
                tokens = usage.get("total_tokens")
                input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
                output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
                bad_components = (input_tokens is not None or output_tokens is not None) and (
                    type(input_tokens) is not int or type(output_tokens) is not int or
                    input_tokens < 0 or output_tokens < 0 or type(tokens) is not int or
                    tokens < input_tokens + output_tokens)
                if type(tokens) is not int or tokens < 0 or bad_components:
                    missing += 1
                    continue
                total += tokens
                counted[call_id] = tokens
                if usage.get("estimated"):
                    estimated += tokens
                else:
                    reported += tokens
            if not self.baseline.issubset(call_ids):
                raise ValueError("baseline lost")
            if any(call_id not in counted or counted[call_id] < tokens for call_id, tokens in self.floor.items()):
                raise ValueError("ledger regressed")
            return {"rows": len(rows), "totalTokens": total, "reportedTokens": reported,
                    "estimatedTokens": estimated, "missingRows": missing, "countedCalls": counted,
                    "localEmbedding": self.context.get("localEmbedding", {"metering": "unknown"})}
        except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
            return {"error": "usage_unobservable"}

    def position(self) -> dict:
        try:
            connection = sqlite3.connect(self.ledger.as_uri() + "?mode=ro", uri=True, timeout=0.2)
            try:
                rows = connection.execute("SELECT call_id, usage_json FROM llm_calls ORDER BY rowid").fetchall()
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            return {"error": "usage_unobservable"}
        return self._position_from_rows(rows)

    def reason(self, position):
        if position.get("error") or position.get("missingRows"):
            return "usage_unknown"
        if position["totalTokens"] >= self.context["limit"]:
            return "budget_exceeded"
        if position["totalTokens"] >= self.context["pauseAt"]:
            return "budget_pause"
        return None

    def check(self):
        position = self.position()
        reason = self.reason(position)
        if self.blocked.is_set() or reason:
            raise DeliveryError(reason or "budget_blocked", "累计用量已到暂停线或无法观察", "failed")
        return position

    def trip(self, reason: str):
        with self._event_lock:
            if self.blocked.is_set():
                return
            self.blocked.set()
            self.events.append({"event": "blocked", "reason": reason})
            if reason in ("budget_pause", "budget_exceeded"):
                self.events.append({"event": "generation_blocked"})
                return
            try:
                self.stop_control()
                self.events.append({"event": "stop_confirmed"})
            except Exception:
                self.events.append({"event": "stop_failed"})

    @contextmanager
    def watch(self):
        if self.running:
            yield self
            return
        self.check()
        if isinstance(self.stop_control, ProcessStop):
            self.stop_control.verify()
        stop = threading.Event()
        def monitor():
            last, changed = None, time.monotonic()
            while not stop.is_set():
                position = self.position()
                signature = digest(position)
                if signature != last:
                    last, changed = signature, time.monotonic()
                reason = self.reason(position)
                if not reason:
                    self.floor = position["countedCalls"]
                if not reason and time.monotonic() - changed >= self.silent:
                    reason = "usage_stale"
                if reason:
                    self.trip(reason)
                    return
                stop.wait(self.interval)
        self.running = True
        thread = threading.Thread(target=monitor, name="learning-book-budget", daemon=True)
        thread.start()
        try:
            try:
                yield self
            except BaseException as exc:
                if not (isinstance(exc, DeliveryError) and exc.code in ("http_401", "http_403", "http_409", "http_422")):
                    self.trip("operation_aborted")
                raise
            if self.reason(self.position()):
                self.trip("final_usage_check")
        finally:
            stop.set()
            thread.join(timeout=6)
            self.running = False
            if thread.is_alive():
                self.blocked.set()
                self.events.append({"event": "monitor_stop_failed"})
        if self.blocked.is_set():
            raise DeliveryError("budget_stopped", "预算门禁已锁住新增调用；后端是否停止须检查停止证据", "uncertain")


def load_budget(path: Path | str | None, scope: dict) -> Budget | None:
    return Budget(read_json(path), scope) if path else None
