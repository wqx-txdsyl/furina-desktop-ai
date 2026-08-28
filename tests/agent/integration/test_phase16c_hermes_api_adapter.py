# -*- coding: utf-8 -*-
"""Phase 16C — Hermes API Backend Adapter 测试（fake HTTP/SSE 全行为锁定）。

权威 recon（本机 Hermes Agent v0.20.6 / upstream 4e7eb399 实测 + 源码）：

- POST /v1/runs → 202 {"run_id":"run_<hex>","status":"started"}；
- GET /v1/runs/{id} → {"object":"hermes.run",…}，status ∈ queued/running/
  waiting_for_approval/stopping/completed/cancelled/failed；
- GET /v1/runs/{id}/events → text/event-stream：``data: {json}\\n\\n`` 帧 +
  ``: keepalive`` 心跳 + ``: stream closed`` 哨兵；
- POST /v1/runs/{id}/approval → 200 {"object":"hermes.run.approval_response",…}
  / 409 approval_not_pending；
- POST /v1/runs/{id}/stop → 200 {"run_id","status":"stopping"}（≠ CANCELLED）。

任务书 §7 十二项最低锁定（全部以确定性 fake HTTP/SSE server 承载）+ 真实协议形态、
身份精确绑定、断线零重复 submit、approval 绝不 always/session、非 loopback 与
URL 凭证拒绝、3xx 非本地重定向 fail-closed、C1–C7 零依赖。
"""
from __future__ import annotations

import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

import pytest

from furina.agent.approval import ApprovalBroker, ApprovalDecisionKind, ApprovalState
from furina.agent.backend import (
    BackendHealth,
    BackendRunHandle,
    BackendScopeViolation,
    ExecutionBackend,
    ExecutionBackendRegistry,
    HermesConfigurationError,
    HermesExecutionBackend,
    HermesProtocolError,
    HermesTransportError,
    TechnicalRouter,
)
from furina.agent.events import (
    BackendEventNormalizer,
    EventKind,
    WorkExecutionReducer,
    WorkExecutionState,
)

CONTRACT_ID = "wc_16c_test_001"
CONTENT_HASH = "a" * 64


# ================================================================ fake Hermes API Server
class _FakeHermesHandler(BaseHTTPRequestHandler):
    """确定性 fake Hermes：默认形状 = 本机 0.20.6 实测；行为由 server 脚本面驱动。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: D401 —— 静默
        pass

    def _record(self, body: Optional[Dict[str, Any]] = None) -> None:
        self.server.requests.append({
            "method": self.command,
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": body,
        })

    def _auth_ok(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.server.api_key}"

    def _unauthorized(self) -> None:
        self._send_json(401, {"error": {"message": "Invalid gateway API key (API_SERVER_KEY)",
                                        "type": "gateway_auth_error",
                                        "code": "gateway_auth_failed"}})

    def _not_found_run(self, run_id: str) -> None:
        self._send_json(404, {"error": {"message": f"Run not found: {run_id}",
                                        "code": "run_not_found"}})

    def _send_json(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except Exception:
            pass

    def _send_sse(self, run_id: str) -> None:
        """SSE 流：按脚本动作序列逐帧写出（分片/心跳/协调等待/断线均可脚本化）。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        script: List[Any] = list(self.server.sse.get(run_id, [("heartbeat",), ("close",)]))
        try:
            for action in script:
                kind = action[0]
                if kind == "frame":
                    payload = dict(action[1])
                    payload.setdefault("run_id", run_id)
                    self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
                elif kind == "fragment":
                    payload = dict(action[1])
                    payload.setdefault("run_id", run_id)
                    line = f"data: {json.dumps(payload)}\n\n".encode("utf-8")
                    n = max(2, int(action[2]))
                    size = max(1, len(line) // n)
                    for i in range(0, len(line), size):
                        self.wfile.write(line[i:i + size])
                        self.wfile.flush()
                        time.sleep(0.005)
                elif kind == "heartbeat":
                    self.wfile.write(b": keepalive\n\n")
                elif kind == "raw":
                    self.wfile.write(action[1])
                elif kind == "sleep":
                    time.sleep(float(action[1]))
                elif kind == "wait_event":
                    action[1].wait(timeout=10.0)
                elif kind == "overrun_line":
                    self.wfile.write(b"data: " + b"x" * (300 * 1024) + b"\n\n")
                elif kind == "close":
                    return
                self.wfile.flush()
        except Exception:
            pass

    def do_GET(self):  # noqa: N802
        self._record()
        path = self.path
        if path == "/health":
            status, body = self.server.health
            self._send_json(status, body)
            return
        if path == "/v1/capabilities":
            if not self._auth_ok():
                self._unauthorized()
                return
            status, body = self.server.capabilities
            self._send_json(status, body)
            return
        if path.startswith("/v1/runs/") and path.endswith("/events"):
            run_id = path[len("/v1/runs/"):-len("/events")]
            if not self._auth_ok():
                self._unauthorized()
                return
            seq = self.server.run_status.get(run_id)
            if seq and seq[0][0] == 404:
                self._not_found_run(run_id)
                return
            if run_id not in self.server.runs:
                self._not_found_run(run_id)
                return
            self._send_sse(run_id)
            return
        if path.startswith("/v1/runs/"):
            run_id = path[len("/v1/runs/"):]
            if not self._auth_ok():
                self._unauthorized()
                return
            seq = self.server.run_status.get(run_id)
            if seq:
                code, body = seq.pop(0) if len(seq) > 1 else seq[0]
            elif run_id in self.server.runs:
                code, body = 200, self.server.runs[run_id]
            else:
                self._not_found_run(run_id)
                return
            self._send_json(code, body)
            return
        self._send_json(404, {"error": {"message": "not found", "code": "not_found"}})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body_req = json.loads(raw) if raw else {}
        except Exception:
            body_req = {}
        self._record(body_req)
        if not self._auth_ok():
            self._unauthorized()
            return
        path = self.path
        if path == "/v1/runs":
            status, body = self.server.submit_response
            if body.get("run_id") == "@auto":
                run_id = f"run_{self.server.wrapper.next_run_id()}"
                body = {**body, "run_id": run_id}
                self.server.wrapper.register_run(run_id)
            self._send_json(status, body)
            return
        if path.startswith("/v1/runs/") and path.endswith("/approval"):
            run_id = path[len("/v1/runs/"):-len("/approval")]
            self.server.approval_requests.append((run_id, dict(body_req)))
            status, body = self.server.approval_response.get(
                run_id,
                (200, {"object": "hermes.run.approval_response", "run_id": run_id,
                       "choice": body_req.get("choice"), "resolved": 1}))
            self._send_json(status, body)
            return
        if path.startswith("/v1/runs/") and path.endswith("/stop"):
            run_id = path[len("/v1/runs/"):-len("/stop")]
            self.server.stop_requests.append(run_id)
            status, body = self.server.stop_response.get(
                run_id, (200, {"run_id": run_id, "status": "stopping"}))
            self._send_json(status, body)
            return
        self._send_json(404, {"error": {"message": "not found", "code": "not_found"}})


class _FakeHermesServer:
    """线程化 fake server（127.0.0.1 ephemeral；确定性脚本面）。"""

    def __init__(self) -> None:
        self.api_key = "fk_" + ("0123456789abcdef" * 3)
        self.requests: List[Dict[str, Any]] = []
        self.approval_requests: List[Tuple[str, Dict[str, Any]]] = []
        self.stop_requests: List[str] = []
        self._counter = 0
        self._lock = threading.Lock()
        # 默认形状 = 本机实测契约（先建 _http，再经 property 写脚本面）
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHermesHandler)
        self._http.wrapper = self
        self.health = (200, {"status": "ok", "platform": "hermes-agent",
                             "version": "0.20.6"})
        self.capabilities = (200, {
            "object": "hermes.api_server.capabilities",
            "platform": "hermes-agent",
            "model": "hermes-agent",
            "auth": {"type": "bearer", "required": True},
            "features": {
                "chat_completions": True,
                "run_submission": True,
                "run_status": True,
                "run_events_sse": True,
                "run_stop": True,
                "run_steer": True,
                "run_approval_response": True,
                "approval_events": True,
                "tool_progress_events": True,
            },
        })
        self.submit_response = (202, {"run_id": "@auto", "status": "started"})
        self.run_status = {}
        self.sse = {}
        self.approval_response = {}
        self.stop_response = {}
        self.runs: Dict[str, Dict[str, Any]] = {}
        self._http.api_key = self.api_key
        self._http.requests = self.requests
        self._http.approval_requests = self.approval_requests
        self._http.stop_requests = self.stop_requests
        self._http.runs = self.runs
        self._thread = threading.Thread(target=self._http.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._http.server_address[:2]
        return f"http://127.0.0.1:{port}"

    # -- 可变脚本面（property 委托到 _http；handler 读的是 _http 自身） --------------
    @property
    def health(self) -> Any:
        return self._http.health

    @health.setter
    def health(self, value: Any) -> None:
        self._http.health = value

    @property
    def capabilities(self) -> Any:
        return self._http.capabilities

    @capabilities.setter
    def capabilities(self, value: Any) -> None:
        self._http.capabilities = value

    @property
    def submit_response(self) -> Any:
        return self._http.submit_response

    @submit_response.setter
    def submit_response(self, value: Any) -> None:
        self._http.submit_response = value

    @property
    def run_status(self) -> Any:
        return self._http.run_status

    @run_status.setter
    def run_status(self, value: Any) -> None:
        self._http.run_status = value

    @property
    def sse(self) -> Any:
        return self._http.sse

    @sse.setter
    def sse(self, value: Any) -> None:
        self._http.sse = value

    @property
    def approval_response(self) -> Any:
        return self._http.approval_response

    @approval_response.setter
    def approval_response(self, value: Any) -> None:
        self._http.approval_response = value

    @property
    def stop_response(self) -> Any:
        return self._http.stop_response

    @stop_response.setter
    def stop_response(self, value: Any) -> None:
        self._http.stop_response = value

    def next_run_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"{self._counter:024x}"

    def register_run(self, run_id: str, status: str = "running") -> None:
        self.runs[run_id] = {"object": "hermes.run", "run_id": run_id,
                             "status": status, "created_at": time.time(),
                             "updated_at": time.time()}

    def set_status_sequence(self, run_id: str,
                            entries: List[Tuple[Any, Any]]) -> None:
        """status 轮询序列：str = 200 + {status}（末条永久重复）；int = 原样状态码。"""
        seq: List[Tuple[int, Any]] = []
        for status, extra in entries:
            if isinstance(status, int):
                seq.append((status, extra))
            else:
                body = {"object": "hermes.run", "run_id": run_id, "status": status,
                        "created_at": time.time(), "updated_at": time.time()}
                body.update(extra or {})
                seq.append((200, body))
        self.run_status[run_id] = seq

    def requests_to(self, path_prefix: str, method: Optional[str] = None) -> List[Dict[str, Any]]:
        return [r for r in self.requests
                if r["path"].startswith(path_prefix)
                and (method is None or r["method"] == method)]

    def shutdown(self) -> None:
        self._http.shutdown()
        self._http.server_close()


# ================================================================ fixtures / helpers
def _projection(**overrides: Any) -> Dict[str, Any]:
    """合法最小 WorkContract projection（与 16A to_backend_projection 字段对齐）。"""
    base: Dict[str, Any] = {
        "contract_id": CONTRACT_ID,
        "content_hash": CONTENT_HASH,
        "canonical_user_request": "在 Hermes 侧完成一个最小探活任务并回显 OK",
        "allowed_backends": ("hermes", "native"),
        "allowed_capabilities": ("cap.filesystem",),
        "workspace_scope": {"read_roots": (), "write_roots": ()},
    }
    base.update(overrides)
    return base


def _make_backend(server: _FakeHermesServer,
                  broker: Optional[ApprovalBroker] = None, **kw: Any) -> HermesExecutionBackend:
    if broker is None:
        broker = ApprovalBroker()
    defaults: Dict[str, Any] = dict(
        base_url=server.base_url,
        api_key=server.api_key,
        approval_broker=broker,
        capability_ids=("cap.filesystem",),
        probe_ttl_seconds=30.0,
        reconnect_poll_interval_seconds=0.05,
        reconnect_poll_budget_seconds=5.0,
        approval_wait_seconds=2.0,
    )
    defaults.update(kw)
    return HermesExecutionBackend(**defaults)


def _drain_events(backend: HermesExecutionBackend, handle: BackendRunHandle,
                  contract_id: str, *, max_events: int = 500):
    """events() 全量消费并同步过 16E（normalizer → reducer）；返回 (records, reducer)。"""
    normalizer = BackendEventNormalizer(backend_id="hermes", contract_id=contract_id,
                                        run_id=handle.run_id)
    reducer = WorkExecutionReducer(handle.run_id, contract_id, backend_id="hermes")
    records = []
    for be in backend.events(handle):
        ne = normalizer.normalize(be)
        res = reducer.reduce(ne)
        records.append((be, ne, res))
        if len(records) >= max_events:
            break
    return records, reducer


def _kinds(records: List[Any]) -> List[str]:
    return [be.event_type for be, _, _ in records]


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def server():
    srv = _FakeHermesServer()
    yield srv
    srv.shutdown()


# ================================================================ 1–2: probe 主动握手
def test_01_probe_active_handshake_success_and_ttl(server):
    """§7.2：主动握手成功（/health + /v1/capabilities + runs 404 握手）；TTL 内走缓存。"""
    backend = _make_backend(server, probe_ttl_seconds=30.0)
    h1 = backend.probe()
    assert isinstance(h1, BackendHealth)
    assert h1.healthy and h1.installed and h1.reachable
    assert h1.expiry > h1.checked_at
    paths = {(r["method"], r["path"]) for r in server.requests}
    assert ("GET", "/health") in paths
    assert ("GET", "/v1/capabilities") in paths
    assert any(r["path"].startswith("/v1/runs/prb_") for r in server.requests), \
        "必须含 runs 面主动握手（probe run_id → 404 run_not_found）"
    n_requests = len(server.requests)
    h2 = backend.probe()
    assert (h2.healthy, h2.installed, h2.reachable, h2.reason) == \
        (h1.healthy, h1.installed, h1.reachable, h1.reason)
    assert len(server.requests) == n_requests, "TTL 内 probe 必须走缓存（零新请求）"
    backend.close()
    # TTL 过期：短 TTL + sleep 后必须重新主动握手（正/负结果同 TTL）
    backend2 = _make_backend(server, probe_ttl_seconds=0.1)
    assert backend2.probe().healthy
    n_before = len(server.requests)
    time.sleep(0.3)
    assert backend2.probe().healthy
    assert len(server.requests) > n_before, "TTL 过期后必须重新主动握手"
    backend2.close()


def test_02_probe_failclosed_matrix(server):
    """§7.1：capability 缺失/说谎/坏载荷/认证失败/形状矛盾/不可达 全部 fail-closed。"""
    good_caps = _FakeHermesServer().capabilities[1]
    # capability 广告缺失（说谎 False）——每个场景用 fresh backend（独立探针缓存）
    server.capabilities = (200, {**good_caps,
                                 "features": {**good_caps["features"],
                                              "run_events_sse": False}})
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "capability_missing:run_events_sse" in h.reason
    backend.close()
    # object 说谎
    server.capabilities = (200, {**good_caps, "object": "something.else"})
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "capabilities_object_contradiction" in h.reason
    backend.close()
    # auth 契约说谎（required=False 与强制 Bearer 矛盾）
    server.capabilities = (200, {**good_caps,
                                 "auth": {"type": "bearer", "required": False}})
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "capabilities_auth_contradiction" in h.reason
    backend.close()
    # 坏载荷（features 非 Mapping）→ fail-closed（typed reason）
    server.capabilities = (200, {"object": "hermes.api_server.capabilities",
                                 "auth": {"type": "bearer", "required": True},
                                 "features": "not-a-mapping"})
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and h.reason.startswith("capabilities_")
    backend.close()
    # 认证失败
    server.capabilities = (401, {"error": {"message": "no",
                                           "code": "gateway_auth_failed"}})
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "auth_rejected" in h.reason
    backend.close()
    # /health 形状矛盾（platform 不是 hermes-agent）
    server.capabilities = (200, good_caps)
    server.health = (200, {"status": "ok", "platform": "someone-else", "version": "9"})
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "health_shape_contradiction" in h.reason
    backend.close()
    # 不可达：连接拒绝（closed port）
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()
    backend2 = _make_backend(server, base_url=f"http://127.0.0.1:{dead_port}")
    h = backend2.probe()
    assert not h.healthy and not h.reachable and "unreachable" in h.reason
    backend2.close()


# ================================================================ 3: submit / correlation
def test_03_submit_protocol_shape_and_correlation(server):
    """§7.3：202 协议形态 + 最小 projection + 幂等 correlation（Hermes 非幂等所有者）。"""
    backend = _make_backend(server)
    assert backend.probe().healthy
    handle = backend.submit(_projection())
    assert isinstance(handle, BackendRunHandle)
    assert handle.backend_id == "hermes"
    assert handle.correlation == CONTRACT_ID
    assert handle.run_id.startswith("run_")
    submits = server.requests_to("/v1/runs", method="POST")
    assert len(submits) == 1
    sent = submits[0]["body"]
    assert sent == {"input": "在 Hermes 侧完成一个最小探活任务并回显 OK"}, \
        f"submit 只允许最小 projection（仅请求文本），实际发送: {sent}"
    assert submits[0]["auth"] == f"Bearer {server.api_key}"
    # 幂等重放：同契约 → 同 handle，零重复 submit
    handle2 = backend.submit(_projection())
    assert handle2 == handle
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    # 同 id 异内容 → 类型化冲突，零新 submit
    with pytest.raises(BackendScopeViolation, match="不同内容摘要"):
        backend.submit(_projection(content_hash="b" * 64))
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    backend.close()


def test_04_submit_failclosed_matrix(server):
    """身份/scope/坏响应全部 fail-closed；失败路径零重试零 fallback。"""
    backend = _make_backend(server)
    bad_projections = [
        _projection(canonical_user_request=""),
        _projection(contract_id=""),
        _projection(content_hash="short"),
        _projection(allowed_backends=("native",)),
        _projection(allowed_capabilities=()),
        _projection(allowed_capabilities=("cap.unknown",)),
        _projection(workspace_scope={"read_roots": ("C:/w/docs",), "write_roots": ()}),
    ]
    for bad in bad_projections:
        with pytest.raises(BackendScopeViolation):
            backend.submit(bad)
    assert not server.requests_to("/v1/runs", method="POST"), \
        "submit 前 fail-closed 必须零 HTTP 请求"
    # 非 202（实测契约：202 started）
    for status, body in ((200, {"run_id": "run_x", "status": "started"}),
                         (500, {"error": {"message": "boom"}}),
                         (429, {"error": {"message": "slow down"}})):
        server.submit_response = (status, body)
        with pytest.raises((HermesProtocolError, HermesTransportError)):
            backend.submit(_projection(contract_id=f"wc_16c_bad_{status}"))
    assert len(server.requests_to("/v1/runs", method="POST")) == 3, "失败路径零重试/零 fallback"
    # 202 但形状非法
    server.submit_response = (202, {"run_id": "@auto"})
    with pytest.raises(HermesProtocolError):
        backend.submit(_projection(contract_id="wc_16c_bad_nostatus"))
    server.submit_response = (202, {"status": "started"})
    with pytest.raises(HermesProtocolError):
        backend.submit(_projection(contract_id="wc_16c_bad_norunid"))
    server.submit_response = (202, {"run_id": "@auto", "status": "queued"})
    with pytest.raises(HermesProtocolError):
        backend.submit(_projection(contract_id="wc_16c_bad_statusword"))
    # 302 非本地重定向 fail-closed
    server.submit_response = (302, {"run_id": "@auto", "status": "started"})
    with pytest.raises(HermesProtocolError, match="redirect"):
        backend.submit(_projection(contract_id="wc_16c_bad_redirect"))
    assert len(server.requests_to("/v1/runs", method="POST")) == 7
    backend.close()


# ================================================================ 5/7: 全生命周期 completed
def test_05_full_lifecycle_completed_maps_unverified(server):
    """§7.7：SSE 真实词表全流程 → 16E BACKEND_DONE_UNVERIFIED；VERIFIED 永不可达。"""
    backend = _make_backend(server)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    server.sse[run_id] = [
        ("frame", {"event": "tool.started", "tool": "terminal", "preview": "echo hello"}),
        ("frame", {"event": "tool.completed", "tool": "terminal", "duration": 0.5,
                   "error": False}),
        ("frame", {"event": "message.delta", "delta": "OK"}),
        ("frame", {"event": "message.delta", "delta": "!"}),
        ("frame", {"event": "run.completed", "output": "OK!",
                   "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}}),
        ("close",),
    ]
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    kinds = _kinds(records)
    # 权威生命周期同步前缀 + SSE 帧
    assert kinds[0] == "queued" and kinds[1] == "running"
    assert kinds.count("run.completed") == 1
    assert "tool.started" in kinds and "tool.completed" in kinds
    assert "message.delta" in kinds
    assert reducer.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    all_states = {r.view.primary for _, _, r in records}
    assert WorkExecutionState.VERIFIED not in all_states
    assert WorkExecutionState.BACKEND_DONE_UNVERIFIED in all_states
    backend.close()


# ================================================================ 4: SSE 分片/心跳
def test_06_sse_fragmentation_and_heartbeat(server):
    """§7.4a：分片帧与心跳不破坏解析；心跳绝不折算事件。"""
    backend = _make_backend(server)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    server.sse[run_id] = [
        ("heartbeat",),
        ("fragment", {"event": "tool.started", "tool": "terminal", "preview": "echo"}, 7),
        ("heartbeat",),
        ("heartbeat",),
        ("fragment", {"event": "run.completed", "output": "done",
                      "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}, 5),
        ("close",),
    ]
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    kinds = _kinds(records)
    assert "tool.started" in kinds
    assert kinds.count("run.completed") == 1
    assert "protocol.error" not in kinds, "分片/心跳不得产生协议错误"
    assert not any("keepalive" in k or "heartbeat" in k for k in kinds)
    assert reducer.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    backend.close()


# ================================================================ 4b: 超限 fail-closed
def test_07_sse_over_limit_failclosed(server):
    """§7.4b：单行超硬上限 → protocol.error + 断流；status reconcile 收口权威终态。"""
    backend = _make_backend(server)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {}), ("completed", {"output": "OK"})])
    server.sse[run_id] = [
        ("overrun_line",),
        ("frame", {"event": "run.completed", "output": "IGNORED-MUST-NOT-PARSE"}),
        ("close",),
    ]
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    kinds = _kinds(records)
    assert "protocol.error" in kinds
    overrun = [be for be, _, _ in records
               if be.event_type == "protocol.error"
               and be.payload.get("reason") == "sse_line_over_limit"]
    assert overrun, "必须报告 sse_line_over_limit"
    # 终态只来自权威 status reconcile（超限断流后 "IGNORED" 帧不再被消费）
    completed = [be for be, _, _ in records if be.event_type == "run.completed"]
    assert len(completed) == 1 and completed[0].payload.get("output") == "OK"
    assert reducer.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    backend.close()


def test_08_sse_bad_frames_failclosed(server):
    """坏 JSON/非 object/缺 event/身份冲突帧 → protocol.error（流继续，零状态变更）。"""
    backend = _make_backend(server)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    server.sse[run_id] = [
        ("raw", b"data: {not json}\n\n"),
        ("raw", b"data: [1,2,3]\n\n"),
        ("raw", b'data: {"no_event": 1}\n\n'),
        ("frame", {"event": "tool.started", "tool": "terminal", "run_id": "run_other"}),
        ("frame", {"event": "tool.started", "tool": "terminal", "preview": "echo hi"}),
        ("frame", {"event": "run.failed", "error": "boom"}),
        ("close",),
    ]
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    reasons = [be.payload.get("reason") for be, _, _ in records
               if be.event_type == "protocol.error"]
    assert "sse_frame_bad_json" in reasons
    assert "sse_frame_not_object" in reasons
    assert "sse_frame_no_event" in reasons
    assert "run_id_mismatch" in reasons
    # 好帧继续被交付
    assert any(be.event_type == "tool.started" and be.payload.get("preview") == "echo hi"
               for be, _, _ in records)
    assert any(be.event_type == "run.failed" for be, _, _ in records)
    # protocol.error 是纯观察（绝不改变 primary 状态；16E 语义：applied no-op）
    prev_state: Optional[WorkExecutionState] = None
    for be, _, r in records:
        if be.event_type == "protocol.error":
            if prev_state is not None:
                assert r.view.primary == prev_state, \
                    f"protocol.error 改变了状态: {prev_state} -> {r.view.primary}"
        prev_state = r.view.primary
    assert reducer.view.primary is WorkExecutionState.FAILED
    backend.close()


def test_09_sse_duplicate_terminal_reducer_absorbs(server):
    """SSE 重复终态帧 → 16E 终态吸收；状态不被二次转移破坏。"""
    backend = _make_backend(server)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    server.sse[run_id] = [
        ("frame", {"event": "run.completed", "output": "OK",
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}),
        ("frame", {"event": "run.completed", "output": "OK",
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}),
        ("close",),
    ]
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    assert _kinds(records).count("run.completed") == 2
    assert reducer.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    # 第二个终态帧（派生 id 视为新到达）在 BACKEND_DONE_UNVERIFIED 上只能自环，
    # 绝不产生二次转移/破坏状态
    second = [r for be, _, r in records
              if be.event_type == "run.completed"][1]
    assert second.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    assert second.diagnostic == ""   # 确认自环，非 illegal/absorbing 拒绝
    backend.close()


# ================================================================ 4c: 断线 reconcile
def test_10_disconnect_reconciles_via_status_no_resubmit(server):
    """§7.4c：SSE 断线 → status 轮询 reconcile → 权威终态；全程零重复 submit。"""
    backend = _make_backend(server)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {}), ("running", {}),
                                        ("completed", {"output": "OK"})])
    server.sse[run_id] = [
        ("frame", {"event": "tool.started", "tool": "terminal", "preview": "echo"}),
        ("close",),   # 中途断线，无终态帧
    ]
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    kinds = _kinds(records)
    assert "transport.reconnected" in kinds
    assert "transport.disconnected" not in kinds
    assert kinds.count("run.completed") == 1
    assert reducer.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    # 断线零重复 submit：整个生命周期只有最初一次 POST /v1/runs
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    # status 轮询真实发生
    assert len(server.requests_to(f"/v1/runs/{run_id}", method="GET")) >= 3
    backend.close()


def test_11_disconnect_unknown_boundary(server):
    """§7.4d：不可恢复断线 / 终态记录被清扫 → 16E UNKNOWN；仍零重复 submit。"""
    backend = _make_backend(server, reconnect_poll_budget_seconds=0.3)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    server.sse[run_id] = [("close",)]
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    assert "transport.disconnected" in _kinds(records)
    assert reducer.view.primary is WorkExecutionState.UNKNOWN
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    # 终态记录已被清扫（status/SSE 均 404）→ UNKNOWN，绝不臆造终态
    n_submits_before = len(server.requests_to("/v1/runs", method="POST"))
    backend2 = _make_backend(server, reconnect_poll_budget_seconds=0.3)
    handle2 = backend2.submit(_projection(contract_id="wc_16c_swept",
                                          content_hash="c" * 64))
    server.set_status_sequence(handle2.run_id, [(404, {"error": {"code": "run_not_found"}})])
    server.sse[handle2.run_id] = [("close",)]
    records2, reducer2 = _drain_events(backend2, handle2, "wc_16c_swept")
    assert reducer2.view.primary is WorkExecutionState.UNKNOWN
    assert any(be.event_type == "transport.disconnected"
               and be.payload.get("reason") == "run_record_swept"
               for be, _, _ in records2)
    assert len(server.requests_to("/v1/runs", method="POST")) == n_submits_before + 1
    backend.close()
    backend2.close()


# ================================================================ 6: stop 不提前 CANCELLED
def test_12_stop_waits_for_authoritative_terminal(server):
    """§7.6：stop 200 stopping ≠ CANCELLED；CANCELLED 只来自 Hermes 权威终态。"""
    backend = _make_backend(server)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    release = threading.Event()
    server.sse[run_id] = [
        ("frame", {"event": "tool.started", "tool": "terminal", "preview": "long task"}),
        ("wait_event", release),
        ("frame", {"event": "run.cancelled"}),
        ("close",),
    ]
    normalizer = BackendEventNormalizer(backend_id="hermes", contract_id=CONTRACT_ID,
                                        run_id=run_id)
    reducer = WorkExecutionReducer(run_id, CONTRACT_ID, backend_id="hermes")
    seen: List[Tuple[str, str]] = []
    lock = threading.Lock()

    def consume() -> None:
        for be in backend.events(handle):
            reducer.reduce(normalizer.normalize(be))
            with lock:
                seen.append((be.event_type, reducer.view.primary.value))

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    assert _wait_until(lambda: bool(seen)), "消费线程必须先建立流"
    backend.stop(handle)
    # stop 200（stopping）之后、Hermes 权威终态之前：绝不出现 CANCELLED
    time.sleep(0.15)
    with lock:
        states_after_stop = {s for _, s in seen}
    assert "CANCELLED" not in states_after_stop, \
        f"stop 成功后绝不提前 CANCELLED: {states_after_stop}"
    assert server.stop_requests == [run_id]
    release.set()
    t.join(timeout=10)
    assert not t.is_alive()
    assert reducer.view.primary is WorkExecutionState.CANCELLED, \
        "权威 run.cancelled 到达后才进入 CANCELLED"
    run_submits = [r for r in server.requests
                   if r["path"] == "/v1/runs" and r["method"] == "POST"]
    assert len(run_submits) == 1, "stop 零重复 submit"
    backend.close()


def test_12b_stop_response_contract_shape(server):
    """stop 响应必须符合实测契约（200 stopping + run_id 回显）；404 → 类型化失败。"""
    backend = _make_backend(server)
    handle = backend.submit(_projection())
    backend.stop(handle)
    assert server.stop_requests == [handle.run_id]
    server.stop_response[handle.run_id] = (404, {"error": {"code": "run_not_found"}})
    with pytest.raises(HermesTransportError, match="不声明 CANCELLED"):
        backend.stop(handle)
    backend.close()


# ================================================================ 5: approval 走 16D
def test_13_approval_resolved_via_16d_forwards_once(server):
    """§7.5a：approval.request → 16D 请求建立；真实 APPROVE_ONCE 决议 → 只转发 once。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    backend = _make_backend(server, broker=broker)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("waiting_for_approval", {}), ("running", {})])
    approved = threading.Event()
    server.sse[run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo OK", "preview": "echo OK"}),
        ("wait_event", approved),
        ("frame", {"event": "tool.started", "tool": "terminal", "preview": "echo OK"}),
        ("frame", {"event": "tool.completed", "tool": "terminal", "duration": 0.1,
                   "error": False}),
        ("frame", {"event": "run.completed", "output": "OK",
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}),
        ("close",),
    ]
    container: Dict[str, Any] = {}

    def consume() -> None:
        normalizer = BackendEventNormalizer(backend_id="hermes", contract_id=CONTRACT_ID,
                                            run_id=run_id)
        reducer = WorkExecutionReducer(run_id, CONTRACT_ID, backend_id="hermes")
        for be in backend.events(handle):
            reducer.reduce(normalizer.normalize(be))
            if be.event_type == "approval.request":
                container["approval_id"] = be.payload.get("approval_id")
            container["final"] = reducer.view.primary

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    assert _wait_until(lambda: "approval_id" in container), "审批事件必须携带 16D approval_id"
    approval_id = container["approval_id"]
    assert broker.state_of(approval_id) is ApprovalState.PENDING
    # Furina 决策面（owner 线程）真实决议
    res = broker.resolve(approval_id, ApprovalDecisionKind.APPROVE_ONCE, reason="同意一次")
    assert res.ok
    approved.set()
    result = backend.resolve_approval(approval_id)
    assert result["choice"] == "once" and result["resolved"] == 1
    t.join(timeout=10)
    assert not t.is_alive()
    # Hermes 只收到 once；全程无 always/session
    assert len(server.approval_requests) == 1
    assert server.approval_requests[0] == (run_id, {"choice": "once"})
    assert container["final"] is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    backend.close()


def test_14_approval_deny_and_timeout_failclosed(server):
    """§7.5b：DENY → deny；未获决议（LATE）→ deny；全程绝不 always/session。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    backend = _make_backend(server, broker=broker, approval_wait_seconds=0.3)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("waiting_for_approval", {})])
    server.sse[run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "rm -rf x", "preview": "rm -rf x"}),
        ("close",),
    ]
    container: Dict[str, Any] = {}

    def consume() -> None:
        normalizer = BackendEventNormalizer(backend_id="hermes", contract_id=CONTRACT_ID,
                                            run_id=run_id)
        reducer = WorkExecutionReducer(run_id, CONTRACT_ID, backend_id="hermes")
        for be in backend.events(handle):
            reducer.reduce(normalizer.normalize(be))
            if be.event_type == "approval.request":
                container["approval_id"] = be.payload.get("approval_id")
                container["waiting"] = reducer.view.primary

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    assert _wait_until(lambda: "approval_id" in container)
    approval_id = container["approval_id"]
    assert _wait_until(
        lambda: container.get("waiting") is WorkExecutionState.WAITING_PERMISSION)
    # DENY 决议 → deny 转发
    assert broker.resolve(approval_id, ApprovalDecisionKind.DENY).ok
    result = backend.resolve_approval(approval_id)
    assert result["choice"] == "deny"
    t.join(timeout=10)
    assert not t.is_alive()
    # 超时：无任何决议 → LATE → fail-closed deny
    handle2 = backend.submit(_projection(contract_id="wc_16c_ap_timeout",
                                         content_hash="d" * 64))
    server.set_status_sequence(handle2.run_id, [("waiting_for_approval", {})])
    server.sse[handle2.run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo y", "preview": "echo y"}),
        ("close",),
    ]
    container2: Dict[str, Any] = {}

    def consume2() -> None:
        normalizer = BackendEventNormalizer(backend_id="hermes",
                                            contract_id="wc_16c_ap_timeout",
                                            run_id=handle2.run_id)
        for be in backend.events(handle2):
            reducer2_ne = normalizer.normalize(be)
            if be.event_type == "approval.request":
                container2["approval_id"] = be.payload.get("approval_id")

    t2 = threading.Thread(target=consume2, daemon=True)
    t2.start()
    assert _wait_until(lambda: "approval_id" in container2)
    result2 = backend.resolve_approval(container2["approval_id"])
    assert result2["choice"] == "deny", "未获 Furina 决议必须 fail-closed 转发 deny"
    t2.join(timeout=10)
    assert not t2.is_alive()
    # 全程零 always/session；两次转发都是 deny
    assert len(server.approval_requests) == 2
    assert all(body.get("choice") == "deny" for _, body in server.approval_requests)
    backend.close()


def test_15_adapter_cannot_self_approve_or_bypass_16d(server):
    """§7.5c：decision 面锁定的 broker 永远等不到决议（适配器不能自批）；16D 身份绑定。"""
    broker = ApprovalBroker(owner_thread_id=None)   # decision 面永久锁定（fail-closed）
    backend = _make_backend(server, broker=broker, approval_wait_seconds=0.2)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("waiting_for_approval", {})])
    server.sse[run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo z", "preview": "echo z"}),
        ("close",),
    ]
    container: Dict[str, Any] = {}

    def consume() -> None:
        for be in backend.events(handle):
            if be.event_type == "approval.request":
                container["approval_id"] = be.payload.get("approval_id")

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    assert _wait_until(lambda: "approval_id" in container)
    approval_id = container["approval_id"]
    result = backend.resolve_approval(approval_id)
    assert result["choice"] == "deny", "decision 面锁定时必须 fail-closed deny（不能自批）"
    t.join(timeout=10)
    assert not t.is_alive()
    assert server.approval_requests[0][1] == {"choice": "deny"}
    # 16D 请求身份绑定本契约（contract_id/hash 来自 submit 账本）
    requested = [e for e in broker.events if e.etype == "approval.requested"]
    assert requested, "16D 必须收到真实审批请求事件"
    payload = dict(requested[0].payload)
    assert payload["contract_id"] == CONTRACT_ID
    assert payload["contract_hash"] == CONTENT_HASH
    assert payload["run_id"] == run_id
    assert payload["provenance"] == "hermes_adapter"
    # 未知 approval_ref 拒绝（身份精确绑定）
    with pytest.raises(HermesProtocolError, match="未知 approval_ref"):
        backend.resolve_approval("apv_deadbeefdeadbeef")
    backend.close()


# ================================================================ 8/9: 秘密零泄漏
def test_16_secret_redaction_no_leak(server):
    """§7.9：payload 秘密经 16E 信封脱敏；错误文本/API key 零泄漏。"""
    backend = _make_backend(server)
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    server.sse[run_id] = [
        ("frame", {"event": "run.failed",
                   "error": "auth failed: password=hunter2 token=abc123 "
                            "Authorization: Bearer sk-live-secret"}),
        ("close",),
    ]
    normalizer = BackendEventNormalizer(backend_id="hermes", contract_id=CONTRACT_ID,
                                        run_id=run_id, max_payload_bytes=4096)
    reducer = WorkExecutionReducer(run_id, CONTRACT_ID, backend_id="hermes")
    normalized = []
    for be in backend.events(handle):
        normalized.append(normalizer.normalize(be))
        reducer.reduce(normalized[-1])
    failed = [ne for ne in normalized if ne.kind is EventKind.BACKEND_FAILED]
    assert failed
    payload_text = str(failed[0].to_dict())
    for secret in ("hunter2", "abc123", "sk-live-secret", server.api_key):
        assert secret not in payload_text, f"秘密 {secret!r} 泄漏进 16E 信封"
    assert "[REDACTED]" in payload_text
    assert reducer.view.primary is WorkExecutionState.FAILED
    # 认证失败错误文本零 API key
    server.submit_response = (401, {"error": {"message": "bad key"}})
    with pytest.raises(HermesTransportError) as exc_info:
        backend.submit(_projection(contract_id="wc_16c_leak", content_hash="e" * 64))
    assert server.api_key not in str(exc_info.value)
    backend.close()


# ================================================================ 10: 端点封闭集
def test_17_no_cli_proxy_webhook_fallback(server):
    """§7.10：全部通信只在封闭端点集；失败路径无任何其它通道 fallback。"""
    backend = _make_backend(server)
    backend.probe()
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {}), ("failed", {"error": "x"})])
    server.sse[run_id] = [("frame", {"event": "run.failed", "error": "x"}), ("close",)]
    list(backend.events(handle))
    backend.stop(handle)
    for r in server.requests:
        p = r["path"]
        assert (p == "/health" or p == "/v1/capabilities"
                or p.startswith("/v1/runs")), f"越界端点请求: {p}"
        assert "?" not in p and "proxy" not in p and "webhook" not in p \
            and "chat" not in p and "completions" not in p
    # submit 失败后没有任何其它端点尝试
    n_before = len(server.requests)
    server.submit_response = (500, {"error": {"message": "down"}})
    with pytest.raises(HermesTransportError):
        backend.submit(_projection(contract_id="wc_16c_fb", content_hash="f" * 64))
    new_requests = server.requests[n_before:]
    assert new_requests and all(r["path"] == "/v1/runs" for r in new_requests)
    backend.close()


# ================================================================ 4e: 身份精确绑定
def test_18_identity_binding_strict(server):
    """身份精确绑定：外来 handle / 未知 run / 外来 approval_ref 全部类型化拒绝。"""
    backend = _make_backend(server)
    handle = backend.submit(_projection())
    foreign = BackendRunHandle(backend_id="native", run_id=handle.run_id)
    with pytest.raises(HermesProtocolError, match="backend_id"):
        list(backend.events(foreign))
    with pytest.raises(HermesProtocolError, match="backend_id"):
        backend.stop(foreign)
    unknown = BackendRunHandle(backend_id="hermes", run_id="run_neverseen123")
    with pytest.raises(HermesProtocolError, match="未知 hermes run"):
        list(backend.events(unknown))
    with pytest.raises(HermesProtocolError, match="未知 hermes run"):
        backend.stop(unknown)
    with pytest.raises(HermesProtocolError, match="未知 approval_ref"):
        backend.resolve_approval("apv_unknown0000")
    backend.close()


# ================================================================ 5c: loopback / URL 纪律
def test_19_loopback_and_url_discipline(server):
    """§5：默认仅 loopback；URL 凭证/https/query/path/非 loopback 构造期拒绝。"""
    broker = ApprovalBroker()
    bad_urls = [
        "http://10.1.2.3:8642",
        "http://hermes.example.com",
        "https://127.0.0.1:8642",
        "http://user:pass@127.0.0.1:8642",
        "http://127.0.0.1:8642/api?key=x",
        "http://127.0.0.1:8642/v1#frag",
        "http://127.0.0.1:8642/subpath",
        "ftp://127.0.0.1:8642",
        "",
    ]
    for url in bad_urls:
        with pytest.raises(HermesConfigurationError):
            HermesExecutionBackend(base_url=url, api_key="k" * 16, approval_broker=broker)
    with pytest.raises(HermesConfigurationError):
        HermesExecutionBackend(base_url=server.base_url, api_key="k" * 16,
                               approval_broker="not-a-broker")
    with pytest.raises(HermesConfigurationError):
        HermesExecutionBackend(base_url=server.base_url, api_key="",
                               approval_broker=broker)
    with pytest.raises(HermesConfigurationError):
        HermesExecutionBackend(base_url=server.base_url, api_key="k" * 16,
                               approval_broker=broker, probe_ttl_seconds=-1)
    with pytest.raises(HermesConfigurationError):
        HermesExecutionBackend(base_url=server.base_url, api_key="k" * 16,
                               approval_broker=broker, max_event_bytes=1)


# ================================================================ 12: registry/router interop
def test_20_native_regression_and_router_interop(server):
    """§7.12：registry/router 与 hermes/native 并存；workspace 诚实边界；16B 语义不变。"""
    registry = ExecutionBackendRegistry()
    backend = _make_backend(server)
    registry.register(backend)
    registry.register(_StaticNativeForInterop())
    with pytest.raises(Exception):
        registry.register(backend)   # 重复 id 拒绝（16B 语义不变）
    empty_contract = _RouterContract()
    # 未 probe → 不可路由（16B fail-closed 语义不变）
    decision = TechnicalRouter(registry).route(empty_contract)
    assert not decision.ok and decision.refusal_code == "no_compatible_backend"
    registry.probe("hermes")
    decision = TechnicalRouter(registry).route(empty_contract)
    assert decision.ok and decision.backend_id == "hermes"
    # 携带路径 scope 的契约：hermes 机制性拒绝（workspace_scoped=False 诚实声明）
    from furina.agent.work_contract import WorkspaceScope
    scoped = _RouterContract(workspace=WorkspaceScope(read_roots=("C:\\w\\docs",),
                                                      write_roots=("C:\\w\\out",)))
    decision = TechnicalRouter(registry).route(scoped)
    assert not decision.ok
    assert "hermes:workspace_incompatible" in decision.refusal_detail
    backend.close()


class _RouterContract:
    """router interop 最小 contract 视图（duck-type 16A 路由输入面）。"""

    def __init__(self, workspace: Any = None) -> None:
        self.allowed_backends = ("hermes", "native")
        self.allowed_capabilities = ("cap.filesystem",)
        if workspace is not None:
            self.workspace_scope = workspace
        else:
            from furina.agent.work_contract import WorkspaceScope
            self.workspace_scope = WorkspaceScope()

    def to_backend_projection(self) -> Dict[str, Any]:
        return _projection()


class _StaticNativeForInterop(ExecutionBackend):
    """16B 语义 smoke：静态 descriptor/capabilities 的 native 形 backend。"""

    @property
    def descriptor(self):
        from furina.agent.backend import BackendDescriptor
        return BackendDescriptor(backend_id="native", display_name="Native")

    @property
    def capabilities(self):
        from furina.agent.backend import BackendCapabilities
        return BackendCapabilities(capability_ids=("cap.filesystem",),
                                   supports_events=False, supports_stop=False,
                                   supports_resolve_approval=False,
                                   workspace_scoped=True)

    def probe(self) -> BackendHealth:
        now = time.time()
        return BackendHealth(installed=True, reachable=True, healthy=True,
                             checked_at=now, expiry=now + 30.0)

    def submit(self, contract_projection, *, run_id=None) -> BackendRunHandle:
        return BackendRunHandle(backend_id="native", run_id="run_local_native")


# ================================================================ 11: 资源清理
def test_21_close_and_generator_cleanup(server):
    """§7.11：close 幂等；生成器提前关闭（cancel-safe）；close 后仍可重新探活。"""
    backend = _make_backend(server)
    backend.probe()
    handle = backend.submit(_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    release = threading.Event()
    server.sse[run_id] = [("frame", {"event": "tool.started", "tool": "t"}),
                          ("wait_event", release)]
    stream = backend.events(handle)
    first = next(stream)
    assert first.event_type in ("queued", "running", "tool.started")
    stream.close()   # 提前关闭（取消安全：finally 关闭 response）
    release.set()
    backend.close()
    backend.close()   # 幂等
    assert backend.probe().healthy
    backend.close()


# ================================================================ 8b: C1–C7 隔离
def test_22_no_cognition_persona_db_dependency(server):
    """§7.8：16C 模块零 cognition/db/shell 依赖；端点封闭集恰为 7 个 method+path。"""
    import furina.agent.backend.hermes as hermes_mod
    with open(hermes_mod.__file__, encoding="utf-8") as f:
        source = f.read()
    for forbidden in ("import sqlite3", "subprocess", "os.system", "furina.db",
                      "furina.cognition", "from furina.persona", "from furina.memory",
                      "urllib.request", "requests.post"):
        assert forbidden not in source, f"16C 模块出现禁止依赖: {forbidden}"
    paths = set(re.findall(r'_PATH_[A-Z_]+ = "([^"]+)"', source))
    assert paths == {"/health", "/v1/capabilities", "/v1/runs", "/v1/runs/{run_id}",
                     "/v1/runs/{run_id}/events", "/v1/runs/{run_id}/approval",
                     "/v1/runs/{run_id}/stop"}
