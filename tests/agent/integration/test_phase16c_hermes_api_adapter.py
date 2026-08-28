# -*- coding: utf-8 -*-
"""Phase 16C — Hermes API Backend Adapter 测试（fake HTTP/SSE 全行为锁定）。

权威 recon（本机 Hermes Agent v0.20.6 / upstream 4e7eb399 实测 + 源码）：

- POST /v1/runs → 202 {"run_id":"run_<hex>","status":"started"}（body 无 toolset/profile
  限定参数）；
- GET /v1/capabilities → object=hermes.api_server.capabilities + auth + features + model
  （model = active profile 身份广告，非 default/custom profile 名进入 model）；
- GET /v1/toolsets → {"object":"list","platform":"api_server","data":[{name,enabled,
  configured,tools:[…]}]} —— api_server 平台实际暴露给 run agent 的工具面；
- GET /v1/runs/{id} → {"object":"hermes.run",…}，status ∈ queued/running/
  waiting_for_approval/stopping/completed/cancelled/failed；
- GET /v1/runs/{id}/events → text/event-stream：``data: {json}\\n\\n`` 帧 +
  ``: keepalive`` 心跳 + ``: stream closed`` 哨兵；
- POST /v1/runs/{id}/approval → 200 {"object":"hermes.run.approval_response",…}
  / 409 approval_not_pending·approval_not_active / 400 invalid_approval_choice /
  404 run_not_found；
- POST /v1/runs/{id}/stop → 200 {"run_id","status":"stopping"}（≠ CANCELLED）；
- 不存在 run_id 上 status/events/approval/stop 四端点 → 全部 404 run_not_found
  且零副作用（probe 无副作用主动握手面）。

Reviewer Patch 1 锁定面：完整 WorkContract projection（16A exact-schema + content_hash
完整性摘要复核）为唯一合法 submit 主路径、expected profile identity 绑定、capability
envelope 封闭相等、approval 完整操作身份 + exactly-once 转发、submit 原子 reservation
单 POST、max_concurrent_runs/账本硬容量、status 身份封闭、content-type/错误码精确校验、
SSE 严格 UTF-8 + 超限 discard-until-blank、裸 key 值脱敏、lying capabilities probe
unhealthy。

Reviewer Patch 2 锁定面：expected_profile_tools 构造期封闭（probe 工具面精确相等——
多/少/未知/坏类型 unhealthy；platform==api_server）、submit 要求新鲜健康 probe
（未 probe/probe 过期 → 零 POST，不自动补）、可信 contract authorizer（未知 id/hash/
异常/非 True → submit 前拒绝零 HTTP）、run 账本 POST 前容量预留（满 → 零 POST）、
202 run_id 属他契约不覆盖（typed conflict + reservation 中毒）、events/stop correlation
精确校验、approval 容量/预留/broker 创建/入账封闭状态机（并发 cap=1 最终 ≤1）、
once 转发立即边界 = PermitIssuer.issue + broker.consume_permit 原子复核消费
（决议与远端边界之间撤销 → 绝不 once）、精确媒体类型（application/json 仅容 charset）、
流式有界 JSON 读取（4MiB 立即拒绝；错误体 64KiB 有界；超限内容不入异常）。

Reviewer Patch 3 锁定面：**16D 四层 Gate 恢复**——PermitIssuer 直接持有/注册/issue
全部删除（源码结构断言），approval.request 一律经对应契约 ApprovalGate.check_step
（完整 WorkContract + 真实原始 args + 实时 permission_decider 的 PermissionDecision +
冻结 envelope + risk 下界 L2 + wait_for_approval=false）；仅 APPROVAL_PENDING 建立
待审批记录；resolve 重新取得 PermissionDecision 并再次调用同一 Gate.check_step——
GateResult=ALLOW + permit + gate.consume_permit 原子消费成功才 POST once（PM DENY/
降级、Gate 契约 hash 不匹配、撤销、消费失败一律 deny 零 once）；**工具面全等闭合**
（set(tool_capability_map.keys()) == set(expected_profile_tools)——多/少/未知/空白/
未规范化名字构造期拒绝；approval.request 要求 tool ∈ probe 快照 ∩ expected ∩ 映射）；
**HTTP 真正有界**（读取异常抛类型化错误绝不返回前缀；单 chunk extend 前检查余量；
错误码 JSON 同样要求精确 application/json——text/plain 的 run_not_found/
approval_not_pending 不当作已知错误码；超限内容不入异常文本/日志/缓冲）。

Reviewer Patch 5 锁定面：**Gate→ApprovalBroker 绑定证明完整身份化**——仅"同名 ID
存在/激活"不构成证明：approval 路径经 claimed ApprovalRequest 字段独立重算
（scope/risk/policy 不信任 Gate 自报）+ 主 broker 公开全身份查询面
``matching_request``（含 broker 密钥 HMAC operation_digest）、命中 approval_id
**精确等于** Gate 返回值；grant 路径经主 broker 公开查询面 ``covering_grant``
全匹配（contract/tool/capability/paths/write_paths）、有效 grant_id **精确等于**
Gate 返回值；UUID 碰撞 / 换 args / 换 run_id / 换契约 hash / 换 scope 一律
fail-closed deny（不进账本、不消费 permit、零 once、原记录不覆盖不串用）；
resolve 边界 once 前同样先绑定证明；``_deep_freeze_json`` 只接受真正 JSON 值域
（tuple 不得静默转 list → ``approval_args_not_canonical``）。
"""
from __future__ import annotations

import ast
import json
import re
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

import pytest

from furina.agent.approval import (
    ApprovalBroker,
    ApprovalDecisionKind,
    ApprovalGate,
    ApprovalState,
    EvidenceContext,
)
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
from furina.agent.backend import hermes as hermes_module
from furina.agent.backend.hermes import _RunRecord   # 白盒：并发容量攻击确定性驱动
from furina.agent.events import (
    BackendEventNormalizer,
    EventKind,
    WorkExecutionReducer,
    WorkExecutionState,
)
from furina.agent.permission import Permission, PermissionDecision
from furina.agent.work_contract import (
    ApprovalPolicyRef,
    CostBudget,
    ExecutionBudget,
    VerificationStandard,
    WorkspaceScope,
    WorkContract,
)

CONTRACT_ID = "wc_16c_test_001"
PROFILE_ID = "hermes-agent"
#: 封闭映射覆盖 fake server 默认 enabled 工具面（bash/terminal/process/read_file/
#: write_file）——expected_profile_tools 默认 = 映射键全集，归属集 == envelope。
DEFAULT_TOOL_MAP = {
    "bash": "cap.filesystem",
    "terminal": "cap.filesystem",
    "process": "cap.filesystem",
    "read_file": "cap.filesystem",
    "write_file": "cap.filesystem",
}
DEFAULT_PROFILE_TOOLS = tuple(sorted(DEFAULT_TOOL_MAP))


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

    def _send_raw(self, status: int, content_type: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
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
        if path == "/v1/toolsets":
            if not self._auth_ok():
                self._unauthorized()
                return
            status, body = self.server.toolsets
            self._send_json(status, body)
            return
        if path.startswith("/v1/runs/") and path.endswith("/events"):
            run_id = path[len("/v1/runs/"):-len("/events")]
            if not self._auth_ok():
                self._unauthorized()
                return
            override = self.server.route_override.get("events")
            if override is not None:
                self._send_json(override[0], override[1])
                return
            raw = self.server.route_override_raw.get("events")
            if raw is not None:
                self._send_raw(raw[0], raw[1], raw[2])
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
            override = self.server.route_override.get("status")
            if override is not None:
                self._send_json(override[0], override[1])
                return
            raw = self.server.route_override_raw.get("status")
            if raw is not None:
                self._send_raw(raw[0], raw[1], raw[2])
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
            if self.server.drop_next_submit:
                self.server.drop_next_submit = False
                self.close_connection = True
                return   # 不给任何响应：客户端侧"结果不确定"
            if self.server.submit_delay > 0:
                time.sleep(self.server.submit_delay)
            if self.server.submit_abort_raw is not None:
                # Patch 3：先给合法 JSON 前缀（声明完整 Content-Length），随后断流——
                # 客户端"已读前缀即使合法也不得接受"（读取中断 fail-closed）。
                status, ctype, prefix, full = self.server.submit_abort_raw
                self.server.submit_abort_raw = None
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(full)))
                self.end_headers()
                try:
                    self.wfile.write(prefix)
                    self.wfile.flush()
                except Exception:
                    pass
                self.close_connection = True
                return
            if self.server.submit_raw is not None:
                status, ctype, data = self.server.submit_raw
                self.server.submit_raw = None   # one-shot
                self._send_raw(status, ctype, data)
                return
            status, body = self.server.submit_response
            if body.get("run_id") == "@auto":
                run_id = f"run_{self.server.wrapper.next_run_id()}"
                body = {**body, "run_id": run_id}
                self.server.wrapper.register_run(run_id)
            self._send_json(status, body)
            return
        if path.startswith("/v1/runs/") and path.endswith("/approval"):
            run_id = path[len("/v1/runs/"):-len("/approval")]
            if not self._auth_ok():
                self._unauthorized()
                return
            override = self.server.route_override.get("approval")
            if override is not None:
                self._send_json(override[0], override[1])
                return
            raw = self.server.route_override_raw.get("approval")
            if raw is not None:
                self._send_raw(raw[0], raw[1], raw[2])
                return
            if run_id not in self.server.runs:
                self._not_found_run(run_id)   # 零副作用：未知 run 在解析 body 前拒绝
                return
            self.server.approval_requests.append((run_id, dict(body_req)))
            status, body = self.server.approval_response.get(
                run_id,
                (200, {"object": "hermes.run.approval_response", "run_id": run_id,
                       "choice": body_req.get("choice"), "resolved": 1}))
            self._send_json(status, body)
            return
        if path.startswith("/v1/runs/") and path.endswith("/stop"):
            run_id = path[len("/v1/runs/"):-len("/stop")]
            if not self._auth_ok():
                self._unauthorized()
                return
            override = self.server.route_override.get("stop")
            if override is not None:
                self._send_json(override[0], override[1])
                return
            if run_id not in self.server.runs:
                self._not_found_run(run_id)   # 零副作用：未知 run 无 agent/task 可停
                return
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
            "model": PROFILE_ID,
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
        self.toolsets = (200, {
            "object": "list",
            "platform": "api_server",
            "data": [
                {"name": "terminal", "label": "Terminal", "description": "",
                 "enabled": True, "configured": True,
                 "tools": ["bash", "terminal", "process"]},
                {"name": "filesystem", "label": "FS", "description": "",
                 "enabled": True, "configured": True,
                 "tools": ["read_file", "write_file"]},
                {"name": "web", "label": "Web", "description": "",
                 "enabled": False, "configured": False, "tools": ["web_fetch"]},
            ],
        })
        self.submit_response = (202, {"run_id": "@auto", "status": "started"})
        self.submit_delay = 0.0
        self.drop_next_submit = False
        self.submit_raw: Optional[Tuple[int, str, bytes]] = None
        self.submit_abort_raw: Optional[Tuple[int, str, bytes, bytes]] = None
        self.route_override: Dict[str, Tuple[int, Any]] = {}
        self.route_override_raw: Dict[str, Tuple[int, str, bytes]] = {}
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
    def toolsets(self) -> Any:
        return self._http.toolsets

    @toolsets.setter
    def toolsets(self, value: Any) -> None:
        self._http.toolsets = value

    @property
    def submit_response(self) -> Any:
        return self._http.submit_response

    @submit_response.setter
    def submit_response(self, value: Any) -> None:
        self._http.submit_response = value

    @property
    def submit_delay(self) -> float:
        return self._http.submit_delay

    @submit_delay.setter
    def submit_delay(self, value: float) -> None:
        self._http.submit_delay = value

    @property
    def drop_next_submit(self) -> bool:
        return self._http.drop_next_submit

    @drop_next_submit.setter
    def drop_next_submit(self, value: bool) -> None:
        self._http.drop_next_submit = value

    @property
    def submit_raw(self) -> Any:
        return self._http.submit_raw

    @submit_raw.setter
    def submit_raw(self, value: Any) -> None:
        self._http.submit_raw = value

    @property
    def submit_abort_raw(self) -> Any:
        return self._http.submit_abort_raw

    @submit_abort_raw.setter
    def submit_abort_raw(self, value: Any) -> None:
        self._http.submit_abort_raw = value

    @property
    def route_override(self) -> Dict[str, Tuple[int, Any]]:
        return self._http.route_override

    @route_override.setter
    def route_override(self, value: Dict[str, Tuple[int, Any]]) -> None:
        self._http.route_override = value

    @property
    def route_override_raw(self) -> Dict[str, Tuple[int, str, bytes]]:
        return self._http.route_override_raw

    @route_override_raw.setter
    def route_override_raw(self, value: Dict[str, Tuple[int, str, bytes]]) -> None:
        self._http.route_override_raw = value

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

    def requests_to(self, path: str, method: Optional[str] = None) -> List[Dict[str, Any]]:
        return [r for r in self.requests
                if r["path"] == path
                and (method is None or r["method"] == method)]

    def shutdown(self) -> None:
        self._http.shutdown()
        self._http.server_close()


# ================================================================ fixtures / helpers
def _make_contract(contract_id: str = CONTRACT_ID, request: Optional[str] = None,
                   caps: Tuple[str, ...] = ("cap.filesystem",),
                   backends: Tuple[str, ...] = ("hermes", "native"),
                   workspace_scope: Optional[WorkspaceScope] = None) -> WorkContract:
    """真实 16A WorkContract（合法主路径一律经 to_backend_projection）。"""
    return WorkContract(
        contract_id=contract_id,
        contract_version="1.0.0",
        canonical_user_request=request or "在 Hermes 侧完成一个最小探活任务并回显 OK",
        objective="最小探活（16C fake server 行为锁定）",
        commitment_scope_included=("最小探活任务",),
        workspace_scope=workspace_scope or WorkspaceScope(),
        budget=ExecutionBudget(max_duration_seconds=600.0,
                               cost_limit=CostBudget(amount=5.0, currency="CNY"),
                               max_attempts=1),
        verification_standard=VerificationStandard(
            criteria=(), verifier_refs=("furina.verify.hermes_probe",)),
        approval_policy=ApprovalPolicyRef(policy_id="policy_hermes_probe",
                                          policy_kind="approval_required_each_step",
                                          scope_note="仅 16C fake server 行为锁定"),
        source_event_id="lev_1756000000000_deadbeef",
        allowed_capabilities=caps,
        allowed_backends=backends,
    )


def _projection(contract: Optional[WorkContract] = None,
                **overrides: Any) -> Dict[str, Any]:
    """合法 projection = 真实 WorkContract.to_backend_projection 的可变深拷贝。"""
    c = contract if contract is not None else _make_contract()
    d = json.loads(json.dumps(c.to_dict()))   # plain 深拷贝（list/dict/标量）
    for key, value in overrides.items():
        if value is _DELETE:
            d.pop(key, None)
        else:
            d[key] = value
    return d


class _Delete:
    """占位哨兵：_projection(key=_DELETE) 表示删除该键（不完整 projection 用例）。"""


_DELETE = _Delete()


class _label:
    """失败标注上下文（pytest.raises 无 msg 形参；仅用于报告可读性）。"""

    def __init__(self, text: str) -> None:
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            print(f"[case] {self.text}: {exc}")
        return False


def _default_permission_decider(tool: str, capability: str, raw_args: Any,
                                contract_id: str, run_id: str) -> PermissionDecision:
    """测试默认 PM：对任意 Hermes 工具授权 L2（approval 流程可达；granted=False 由
    专项用例用可变 holder 覆写）。"""
    return PermissionDecision(True, "test_pm_allow", Permission.L2_HIGH_RISK)


def _make_gate(broker: ApprovalBroker, contract: WorkContract, *,
               tool_map: Optional[Dict[str, str]] = None,
               gate_kw: Optional[Dict[str, Any]] = None,
               issuer_kw: Optional[Dict[str, Any]] = None) -> ApprovalGate:
    """可信组合根（16D 公开 API）：broker（owner 线程）→ create_permit_issuer →
    ApprovalGate（内部 issuer 绑定契约 id/hash；工具面快照与 backend 封闭映射一致）。"""
    tool_map = tool_map or DEFAULT_TOOL_MAP
    issuer = broker.create_permit_issuer(
        expected_contract_id=contract.contract_id,
        expected_content_hash=contract.content_hash,
        **(issuer_kw or {}))
    return ApprovalGate(capability_snapshot=dict(tool_map), broker=broker,
                        permit_issuer=issuer, **(gate_kw or {}))


def _make_gates(broker: ApprovalBroker, *contracts: WorkContract,
                tool_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """为多个契约批量创建 Gate 映射（contract_id → ApprovalGate）。"""
    return {c.contract_id: _make_gate(broker, c, tool_map=tool_map)
            for c in contracts}


def _make_backend(server: _FakeHermesServer,
                  broker: Optional[ApprovalBroker] = None,
                  contract: Optional[WorkContract] = None, *,
                  preprobe: bool = True,
                  approval_gates: Optional[Dict[str, Any]] = None,
                  permission_decider: Any = None,
                  contract_authorizer: Any = None,
                  **kw: Any) -> HermesExecutionBackend:
    """默认 authorizer 放行一切（合法自哈希契约主路径）；专项用例覆写。
    ``preprobe``：submit 前置 probe 门的默认满足方式（False = 保持"未 probe"状态）。
    Reviewer Patch 3：默认 broker 绑定 owner 线程并注入 Gate（approval 走 16D 四层
    判定）；默认 permission_decider 授权 L2（approval 流程可达）。"""
    if broker is None:
        broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    caps = tuple(contract.allowed_capabilities) if contract is not None \
        else ("cap.filesystem",)
    tool_map = dict(kw.pop("tool_capability_map", DEFAULT_TOOL_MAP))
    if approval_gates is None and contract is not None \
            and broker.owner_thread_id is not None:
        approval_gates = _make_gates(broker, contract, tool_map=tool_map)
    defaults: Dict[str, Any] = dict(
        base_url=server.base_url,
        api_key=server.api_key,
        approval_broker=broker,
        expected_profile_identity=PROFILE_ID,
        expected_profile_tools=kw.pop("expected_profile_tools",
                                      tuple(sorted(tool_map))),
        tool_capability_map=tool_map,
        contract_authorizer=contract_authorizer or (lambda cid, ch: True),
        capability_ids=caps,
        approval_gates=approval_gates,
        permission_decider=permission_decider or _default_permission_decider,
        probe_ttl_seconds=30.0,
        reconnect_poll_interval_seconds=0.05,
        reconnect_poll_budget_seconds=5.0,
        approval_wait_seconds=2.0,
    )
    defaults.update(kw)
    backend = HermesExecutionBackend(**defaults)
    if preprobe:
        # 默认建立一次 probe 事实（submit 前置门只消费既有事实，不自动补 probe）；
        # 脚本面被改成不健康的用例同样缓存其负结果（正/负同 TTL）。
        backend.probe()
    return backend


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
    """主动握手成功（/health + /v1/capabilities + /v1/toolsets + runs 四端点 404 握手）；
    profile 工具面快照捕获；TTL 内走缓存；TTL 过期重新握手。"""
    backend = _make_backend(server, probe_ttl_seconds=30.0)
    h1 = backend.probe()
    assert isinstance(h1, BackendHealth)
    assert h1.healthy and h1.installed and h1.reachable
    assert h1.expiry > h1.checked_at
    paths = {(r["method"], r["path"]) for r in server.requests}
    assert ("GET", "/health") in paths
    assert ("GET", "/v1/capabilities") in paths
    assert ("GET", "/v1/toolsets") in paths
    probe_paths = [r["path"] for r in server.requests if "/v1/runs/prb_" in r["path"]]
    assert any(p.endswith("/events") for p in probe_paths), "events 端点必须主动握手"
    assert any(p.endswith("/approval") for p in probe_paths), "approval 端点必须主动握手"
    assert any(p.endswith("/stop") for p in probe_paths), "stop 端点必须主动握手"
    assert any(not p.endswith(("/events", "/approval", "/stop")) for p in probe_paths), \
        "status 端点必须主动握手"
    assert backend.profile_tools_snapshot == ("bash", "process", "read_file",
                                              "terminal", "write_file"), \
        "probe 必须捕获 enabled 工具面快照（disabled web_fetch 不得进入）"
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
    """capability 缺失/说谎/坏载荷/认证失败/形状矛盾/profile 身份不一致/不可达
    全部 fail-closed。"""
    fresh = _FakeHermesServer()
    good_caps = fresh.capabilities[1]
    good_toolsets = fresh.toolsets
    fresh.shutdown()
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
                                 "model": PROFILE_ID,
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
    # toolsets 端点缺失（dedicated toolset 证据面不可用）→ fail-closed
    server.health = (200, {"status": "ok", "platform": "hermes-agent", "version": "0.20.6"})
    server.toolsets = (404, {"error": {"message": "not found", "code": "not_found"}})
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "toolsets_endpoint_missing" in h.reason
    backend.close()
    # 不可达：连接拒绝（closed port）
    server.toolsets = good_toolsets
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
    """202 协议形态 + 最小 projection（仅请求文本，无 instructions）+
    幂等 correlation（同 id 同 hash 重放同 handle；同 id 异 hash 类型化冲突）。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    assert backend.probe().healthy
    handle = backend.submit(contract.to_backend_projection())
    assert isinstance(handle, BackendRunHandle)
    assert handle.backend_id == "hermes"
    assert handle.correlation == CONTRACT_ID
    assert handle.run_id.startswith("run_")
    submits = server.requests_to("/v1/runs", method="POST")
    assert len(submits) == 1
    sent = submits[0]["body"]
    assert sent == {"input": contract.canonical_user_request}, \
        f"submit 只允许最小 projection（仅请求文本、无 instructions/Persona），实际: {sent}"
    assert submits[0]["auth"] == f"Bearer {server.api_key}"
    # 幂等重放：同契约（重新构造 → created_at 不同但 content_hash 相同）→ 同 handle，
    # 零重复 submit
    replay = _make_contract().to_backend_projection()
    handle2 = backend.submit(replay)
    assert handle2 == handle
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    # 同 id 异内容（自身一致的有效契约）→ 类型化冲突，零新 submit
    conflicting = _make_contract(request="完全不同的请求文本").to_backend_projection()
    with pytest.raises(BackendScopeViolation, match="不同内容摘要"):
        backend.submit(conflicting)
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    backend.close()


def test_04_submit_failclosed_matrix(server):
    """篡改/不完整/未知字段/缺失字段/越权 caps/路径 scope 全部 submit 前拒绝（零 HTTP）；
    坏响应 fail-closed 零重试零 fallback。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    d = contract.to_backend_projection()
    bad_projections = [
        ("空请求文本", _projection(contract, canonical_user_request="")),
        ("空 contract_id", _projection(contract, contract_id="")),
        ("hash 格式非法", _projection(contract, content_hash="short")),
        ("hash 篡改（内容-摘要不符）", _projection(contract, content_hash="b" * 64)),
        ("载荷篡改（canonical_user_request 改动）",
         _projection(contract, canonical_user_request="被篡改的请求")),
        ("未知字段", {**d, "self_granted_power": "root"}),
        ("缺失字段", _projection(contract, objective=_DELETE)),
        # 以下三个用重签过的合法 projection：精确命中 backend 授权检查层
        ("allowed_backends 不含 hermes",
         _make_contract(backends=("native",)).to_backend_projection()),
        ("caps 超 envelope（自签扩权）",
         _make_contract(caps=("cap.filesystem", "cap.evil")).to_backend_projection()),
        ("路径 scope",
         _make_contract(workspace_scope=WorkspaceScope(
             read_roots=("C:/w/docs",))).to_backend_projection()),
    ]
    for label, bad in bad_projections:
        with pytest.raises(BackendScopeViolation), _label(label):
            backend.submit(bad)
    assert not server.requests_to("/v1/runs", method="POST"), \
        "submit 前 fail-closed 必须零 HTTP 请求"
    # 非 202（实测契约：202 started）——每例独立契约（确定性失败不占账本）
    for i, (status, body) in enumerate(((200, {"run_id": "run_x", "status": "started"}),
                                        (500, {"error": {"message": "boom"}}),
                                        (429, {"error": {"message": "slow down"}}))):
        server.submit_response = (status, body)
        with pytest.raises((HermesProtocolError, HermesTransportError)):
            backend.submit(
                _make_contract(contract_id=f"wc_16c_bad_{status}").to_backend_projection())
    assert len(server.requests_to("/v1/runs", method="POST")) == 3, "失败路径零重试/零 fallback"
    # 202 但形状非法（服务器可能已启动 run → 结果不确定；用独立契约）
    server.submit_response = (202, {"run_id": "@auto"})
    with pytest.raises((HermesProtocolError, HermesTransportError)):
        backend.submit(_make_contract(contract_id="wc_16c_bad_nostatus")
                       .to_backend_projection())
    server.submit_response = (202, {"status": "started"})
    with pytest.raises((HermesProtocolError, HermesTransportError)):
        backend.submit(_make_contract(contract_id="wc_16c_bad_norunid")
                       .to_backend_projection())
    server.submit_response = (202, {"run_id": "@auto", "status": "queued"})
    with pytest.raises((HermesProtocolError, HermesTransportError)):
        backend.submit(_make_contract(contract_id="wc_16c_bad_statusword")
                       .to_backend_projection())
    # 302 非本地重定向 fail-closed
    server.submit_response = (302, {"run_id": "@auto", "status": "started"})
    with pytest.raises(HermesProtocolError, match="redirect"):
        backend.submit(_make_contract(contract_id="wc_16c_bad_redirect")
                       .to_backend_projection())
    assert len(server.requests_to("/v1/runs", method="POST")) == 7
    backend.close()


# ================================================================ 5/7: 全生命周期 completed
def test_05_full_lifecycle_completed_maps_unverified(server):
    """SSE 真实词表全流程 → 16E BACKEND_DONE_UNVERIFIED；VERIFIED 永不可达。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
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
    """分片帧与心跳不破坏解析（含多字节 UTF-8 严格解码正路径）；心跳绝不折算事件。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    server.sse[run_id] = [
        ("heartbeat",),
        ("fragment", {"event": "tool.started", "tool": "terminal",
                      "preview": "echo 中文多字节√"}, 7),
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
def test_07_sse_line_over_limit_failclosed(server):
    """单行超硬上限 → protocol.error + 断流；status reconcile 收口权威终态；
    断流后同流后续帧不得复活为业务/终态事件。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
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
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
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
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
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
    """SSE 断线 → status 轮询 reconcile → 权威终态；全程零重复 submit。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
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
    """不可恢复断线 / 终态记录被清扫（404 + 精确 run_not_found）→ 16E UNKNOWN；仍零重复 submit。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract,
                            reconnect_poll_budget_seconds=0.3)
    handle = backend.submit(contract.to_backend_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    server.sse[run_id] = [("close",)]
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    assert "transport.disconnected" in _kinds(records)
    assert reducer.view.primary is WorkExecutionState.UNKNOWN
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    # 终态记录已被清扫（status/SSE 均 404 run_not_found）→ UNKNOWN，绝不臆造终态
    n_submits_before = len(server.requests_to("/v1/runs", method="POST"))
    contract2 = _make_contract(contract_id="wc_16c_swept")
    backend2 = _make_backend(server, contract=contract2,
                             reconnect_poll_budget_seconds=0.3)
    handle2 = backend2.submit(contract2.to_backend_projection())
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
    """stop 200 stopping ≠ CANCELLED；CANCELLED 只来自 Hermes 权威终态。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
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
    """stop 响应必须符合实测契约（200 stopping + run_id 回显）；
    404 仅在错误码精确 run_not_found 时类型化"不声明 CANCELLED"；错误码不符 = 协议矛盾。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
    backend.stop(handle)
    assert server.stop_requests == [handle.run_id]
    server.stop_response[handle.run_id] = (404, {"error": {"code": "run_not_found"}})
    with pytest.raises(HermesTransportError, match="不声明 CANCELLED"):
        backend.stop(handle)
    # 404 但错误码不符 → 绝不按 run_not_found 语义吞掉
    server.stop_response[handle.run_id] = (404, {"error": {"code": "not_found"}})
    with pytest.raises(HermesProtocolError, match="run_not_found"):
        backend.stop(handle)
    backend.close()


# ================================================================ 5: approval 走 16D
def test_13_approval_resolved_via_16d_forwards_once(server):
    """approval.request → 16D 请求建立（tool→capability 封闭映射）；真实 APPROVE_ONCE
    决议 → 发送边界原子 permit 消费（issue + consume_permit）成功 → 只转发 once、
    resolved==1 精确、16D approval 真实消费（消费先于 POST）。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract()
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract))
    handle = backend.submit(contract.to_backend_projection())
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
    assert result["forwarded"] is True
    assert result["consumed"] is True, "once 必须先于 POST 完成 permit 边界原子消费"
    assert result["permit_id"], "结果必须携带边界消费的 permit_id（可观察性）"
    assert broker.is_consumed(approval_id), "APPROVE_ONCE 边界消费必须真实标记 16D approval"
    t.join(timeout=10)
    assert not t.is_alive()
    # Hermes 只收到 once；全程无 always/session
    assert len(server.approval_requests) == 1
    assert server.approval_requests[0] == (run_id, {"choice": "once"})
    assert container["final"] is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    backend.close()


def test_14_approval_deny_and_timeout_failclosed(server):
    """DENY → deny；未获决议（LATE）→ deny；全程绝不 always/session。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract()
    contract_t = _make_contract(contract_id="wc_16c_ap_timeout")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract, contract_t),
                            approval_wait_seconds=0.3, max_concurrent_runs=4)
    handle = backend.submit(contract.to_backend_projection())
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
    contract2 = _make_contract(contract_id="wc_16c_ap_timeout")
    handle2 = backend.submit(contract2.to_backend_projection())
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
            normalizer.normalize(be)
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
    """无外部决议时适配器永远等不到决议（不能自批）：resolve_approval 只等待真实
    Furina 决议（owner 线程决策面），超窗 fail-closed deny；16D 请求身份绑定真实契约。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract()
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_wait_seconds=0.2)
    handle = backend.submit(contract.to_backend_projection())
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
    # 决议只来自外部决策面（owner 线程 broker.resolve）；适配器自身无任何 resolve/
    # 自批路径——不调用 broker.resolve 时 resolve_approval 等不到决议 → fail-closed deny
    result = backend.resolve_approval(approval_id)
    assert result["choice"] == "deny", "无外部决议必须 fail-closed deny（适配器不能自批）"
    t.join(timeout=10)
    assert not t.is_alive()
    assert server.approval_requests[0][1] == {"choice": "deny"}
    # 16D 请求身份绑定本契约（contract_id/hash 来自 submit 账本的真实 WorkContract，
    # 由 ApprovalGate 四层判定路径创建）
    requested = [e for e in broker.events if e.etype == "approval.requested"]
    assert requested, "16D 必须收到真实审批请求事件"
    payload = dict(requested[0].payload)
    assert payload["contract_id"] == CONTRACT_ID
    assert payload["contract_hash"] == contract.content_hash
    assert payload["run_id"] == run_id
    # 未知 approval_ref 拒绝（身份精确绑定）
    with pytest.raises(HermesProtocolError, match="未知 approval_ref"):
        backend.resolve_approval("apv_deadbeefdeadbeef")
    backend.close()


# ================================================================ 8/9: 秘密零泄漏
def test_16_secret_redaction_no_leak(server):
    """payload 秘密经 16E 信封脱敏；错误文本/API key 零泄漏。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
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
        backend.submit(_make_contract(contract_id="wc_16c_leak").to_backend_projection())
    assert server.api_key not in str(exc_info.value)
    backend.close()


# ================================================================ 10: 端点封闭集
def test_17_no_cli_proxy_webhook_fallback(server):
    """全部通信只在封闭端点集；失败路径无任何其它通道 fallback。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    backend.probe()
    handle = backend.submit(contract.to_backend_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {}), ("failed", {"error": "x"})])
    server.sse[run_id] = [("frame", {"event": "run.failed", "error": "x"}), ("close",)]
    list(backend.events(handle))
    backend.stop(handle)
    for r in server.requests:
        p = r["path"]
        assert (p == "/health" or p == "/v1/capabilities" or p == "/v1/toolsets"
                or p.startswith("/v1/runs")), f"越界端点请求: {p}"
        assert "?" not in p and "proxy" not in p and "webhook" not in p \
            and "chat" not in p and "completions" not in p
    # submit 失败后没有任何其它端点尝试
    n_before = len(server.requests)
    server.submit_response = (500, {"error": {"message": "down"}})
    with pytest.raises(HermesTransportError):
        backend.submit(_make_contract(contract_id="wc_16c_fb").to_backend_projection())
    new_requests = server.requests[n_before:]
    assert new_requests and all(r["path"] == "/v1/runs" for r in new_requests)
    backend.close()


# ================================================================ 4e: 身份精确绑定
def test_18_identity_binding_strict(server):
    """身份精确绑定：外来 handle / 未知 run / 外来 approval_ref 全部类型化拒绝。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
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
    """默认仅 loopback；URL 凭证/https/query/path/非法端口/非 loopback 构造期统一
    HermesConfigurationError。"""
    broker = ApprovalBroker()

    def ctor(**kw):
        base = dict(base_url=server.base_url, api_key="k" * 16,
                    approval_broker=broker,
                    expected_profile_identity=PROFILE_ID,
                    expected_profile_tools=DEFAULT_PROFILE_TOOLS,
                    tool_capability_map=dict(DEFAULT_TOOL_MAP),
                    contract_authorizer=lambda cid, ch: True,
                    capability_ids=("cap.filesystem",))
        base.update(kw)
        return HermesExecutionBackend(**base)

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
        # 非法端口：非数字 / 越界 / 负数 —— 统一折为 HermesConfigurationError
        "http://127.0.0.1:notaport",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:0",
        "http://127.0.0.1:-1",
    ]
    for url in bad_urls:
        with pytest.raises(HermesConfigurationError):
            ctor(base_url=url)
    with pytest.raises(HermesConfigurationError):
        ctor(approval_broker="not-a-broker")
    with pytest.raises(HermesConfigurationError):
        ctor(api_key="")
    with pytest.raises(HermesConfigurationError):
        ctor(probe_ttl_seconds=-1)
    with pytest.raises(HermesConfigurationError):
        ctor(max_event_bytes=1)
    # profile 身份缺失 / tool 映射越权 → 构造期拒绝
    with pytest.raises(HermesConfigurationError, match="expected_profile_identity"):
        ctor(expected_profile_identity="")
    with pytest.raises(HermesConfigurationError, match="越权|envelope"):
        ctor(tool_capability_map={"terminal": "cap.evil"})


# ================================================================ 12: registry/router interop
def test_20_native_regression_and_router_interop(server):
    """registry/router 与 hermes/native 并存；workspace 诚实边界；16B 语义不变。"""
    registry = ExecutionBackendRegistry()
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
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
    """close 幂等；生成器提前关闭（cancel-safe）；close 后仍可重新探活。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    backend.probe()
    handle = backend.submit(contract.to_backend_projection())
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
    """16C 模块零 cognition/db/shell 依赖；端点封闭集恰为 8 个 method+path。"""
    import furina.agent.backend.hermes as hermes_mod
    with open(hermes_mod.__file__, encoding="utf-8") as f:
        source = f.read()
    for forbidden in ("import sqlite3", "subprocess", "os.system", "furina.db",
                      "furina.cognition", "from furina.persona", "from furina.memory",
                      "urllib.request", "requests.post"):
        assert forbidden not in source, f"16C 模块出现禁止依赖: {forbidden}"
    paths = set(re.findall(r'_PATH_[A-Z_]+ = "([^"]+)"', source))
    assert paths == {"/health", "/v1/capabilities", "/v1/toolsets", "/v1/runs",
                     "/v1/runs/{run_id}", "/v1/runs/{run_id}/events",
                     "/v1/runs/{run_id}/approval", "/v1/runs/{run_id}/stop"}


# =================================================================================
# ================================ Reviewer Patch 1 专项 ============================
# =================================================================================

# --------------------------------------------------------------- R1: contract 权威
def test_23_reviewer_tampered_or_incomplete_contract_rejected(server):
    """R1-locked：篡改/不完整 WorkContract projection 一律 submit 前拒绝（零 HTTP）；
    合法主路径必须经真实 to_backend_projection。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    # 不完整 projection（旧版手写 dict 形态）不再是合法输入
    with pytest.raises(BackendScopeViolation, match="缺失必需键"):
        backend.submit({"contract_id": CONTRACT_ID,
                        "canonical_user_request": "手工裁剪 dict",
                        "content_hash": "a" * 64,
                        "allowed_backends": ["hermes"],
                        "allowed_capabilities": ["cap.filesystem"]})
    # 未知字段（自签扩权注入）拒绝
    tampered = _projection(contract)
    tampered["operator_override"] = {"allowed_capabilities": ["cap.god"]}
    with pytest.raises(BackendScopeViolation, match="未知字段"):
        backend.submit(tampered)
    # 篡改 hash 拒绝（16A 从不重新签名）
    with pytest.raises(BackendScopeViolation, match="content_hash"):
        backend.submit(_projection(contract, content_hash="c" * 64))
    # 篡改载荷拒绝（重算摘要不符）
    with pytest.raises(BackendScopeViolation, match="content_hash"):
        backend.submit(_projection(contract, objective="被替换的目标"))
    # envelope 封闭相等：多一方（重签合法 projection）也拒绝（不能只证明"是子集"）
    with pytest.raises(BackendScopeViolation, match="封闭相等"):
        backend.submit(_make_contract(
            caps=("cap.filesystem", "cap.filesystem.extra")).to_backend_projection())
    # 合法主路径：真实 projection 全键集 + 内容摘要复核通过
    handle = backend.submit(contract.to_backend_projection())
    assert handle.correlation == CONTRACT_ID
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    backend.close()


def test_24_reviewer_expected_profile_identity_bound(server):
    """R1-locked：probe 必须绑定 expected Hermes profile identity；
    /v1/capabilities 返回的 profile/model 缺失或不一致 → unhealthy。"""
    fresh = _FakeHermesServer()
    good_caps = fresh.capabilities[1]
    fresh.shutdown()
    # model 不一致 → unhealthy
    server.capabilities = (200, {**good_caps, "model": "another-profile"})
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "profile_identity_mismatch" in h.reason
    assert "another-profile" in h.reason and "hermes-agent" in h.reason
    backend.close()
    # model 缺失 → unhealthy（fail-closed）
    caps_no_model = {k: v for k, v in good_caps.items() if k != "model"}
    server.capabilities = (200, caps_no_model)
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "profile_identity_missing" in h.reason
    backend.close()
    # 一致 → healthy，且 profile 身份来自构造期绑定（不可缺省）
    server.capabilities = (200, good_caps)
    backend = _make_backend(server)
    assert backend.probe().healthy
    backend.close()
    with pytest.raises(TypeError):
        HermesExecutionBackend(base_url=server.base_url, api_key=server.api_key,
                               approval_broker=ApprovalBroker(),
                               tool_capability_map=dict(DEFAULT_TOOL_MAP),
                               capability_ids=("cap.filesystem",))


# --------------------------------------------------------------- R1: capability/tool 映射
def test_25_reviewer_capability_tool_escalation_denied(server):
    """R1-locked：未知工具/缺失工具自动 deny（fail-closed，零 16D 请求、零可扩权审批）；
    帧自带 capability 声明不被信任；映射越权构造期拒绝。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract()
    backend = _make_backend(server, broker=broker, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {}), ("completed", {"output": "OK"})])
    server.sse[run_id] = [
        # 未知工具（不在封闭映射内）→ 自动 deny
        ("frame", {"event": "approval.request", "tool": "file_editor",
                   "command": "write /etc/hosts", "preview": "write /etc/hosts"}),
        # 工具缺失 → 自动 deny
        ("frame", {"event": "approval.request", "command": "no tool at all"}),
        # 未知工具 + 帧自带 capability 自签声明 → 仍自动 deny（帧 capability 不被信任）
        ("frame", {"event": "approval.request", "tool": "memory_tool",
                   "capability": "cap.filesystem", "command": "steal secrets"}),
        # 映射内工具 → 正常 16D 请求
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo ok", "preview": "echo ok"}),
        ("frame", {"event": "run.completed", "output": "OK",
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}),
        ("close",),
    ]
    approval_ids: List[str] = []
    for be in backend.events(handle):
        if be.event_type == "approval.request":
            approval_ids.append(be.payload["approval_id"])
    # 三次扩权尝试全部自动 deny（Hermes 收到 3 条 deny + 无 16D 请求）
    denies = [body for _, body in server.approval_requests if body.get("choice") == "deny"]
    assert len(denies) == 3, f"未知/缺失工具必须自动 deny: {server.approval_requests}"
    assert len(approval_ids) == 1, "只有映射内工具才建立 16D 请求"
    requested = [e for e in broker.events if e.etype == "approval.requested"]
    assert len(requested) == 1
    assert dict(requested[0].payload)["tool"] == "terminal"
    assert dict(requested[0].payload)["capability"] == "cap.filesystem"
    # 映射越权（值不在 envelope 内）构造期拒绝——不向可扩权映射开放
    with pytest.raises(HermesConfigurationError):
        _make_backend(server, contract=contract,
                      tool_capability_map={"terminal": "cap.filesystem",
                                           "god_tool": "cap.omnipotence"})
    backend.close()


# --------------------------------------------------------------- R2: approval exact identity
def test_26_reviewer_same_preview_different_command_distinct_approvals(server):
    """R2-locked：同 tool 同 preview、不同 command ⇒ 不同 operation digest ⇒ 不同
    16D approval（(tool, preview) 有损身份缓存已废除）；相同操作帧幂等复用。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract()
    backend = _make_backend(server, broker=broker, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {}), ("completed", {"output": "OK"})])
    server.sse[run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "preview": "echo OK", "command": "echo OK"}),
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "preview": "echo OK", "command": "echo OK; rm -rf /tmp/x"}),
        # 完全相同的操作帧 → broker 原子 get-or-create 幂等复用同一 approval
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "preview": "echo OK", "command": "echo OK"}),
        ("frame", {"event": "run.completed", "output": "OK",
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}),
        ("close",),
    ]
    seen: List[str] = []
    for be in backend.events(handle):
        if be.event_type == "approval.request":
            seen.append(be.payload["approval_id"])
    assert len(seen) == 3
    assert seen[0] != seen[1], "同 preview 不同 command 必须得到不同 approval"
    assert seen[0] == seen[2], "完全相同的操作帧必须幂等复用同一 approval"
    requested = [e for e in broker.events if e.etype == "approval.requested"]
    assert len(requested) == 2, "16D 只创建两个不同操作身份的请求"
    backend.close()


def test_27_reviewer_approval_forward_exactly_once(server):
    """R2-locked：同一 approval 顺序重复/并发 resolve 只有一个 Hermes POST；
    第二次调用 typed no-op；409 仅精确 approval_not_pending 才是 no-op。
    Patch 2：once 主路径全部经 permit 立即边界原子消费（五个契约均注入 issuer）。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract()
    contract2 = _make_contract(contract_id="wc_16c_concurrent_ap")
    contract3 = _make_contract(contract_id="wc_16c_409_exact")
    contract4 = _make_contract(contract_id="wc_16c_409_wrong")
    contract5 = _make_contract(contract_id="wc_16c_resolved0")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(
                                broker, contract, contract2, contract3, contract4,
                                contract5),
                            reconnect_poll_budget_seconds=0.5, max_concurrent_runs=8)
    handle = backend.submit(contract.to_backend_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("waiting_for_approval", {})])
    server.sse[run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo once", "preview": "echo once"}),
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
    assert broker.resolve(approval_id, ApprovalDecisionKind.APPROVE_ONCE).ok
    # 顺序重复：第二次 typed no-op，零新 POST
    first = backend.resolve_approval(approval_id)
    assert first["forwarded"] is True and first["resolved"] == 1
    second = backend.resolve_approval(approval_id)
    assert second["forwarded"] is False and second["resolved"] == 0, \
        "重复 resolve 必须 typed no-op"
    # 并发 resolve：单请求获胜，只有一个 POST
    server.approval_requests.clear()
    contract2 = _make_contract(contract_id="wc_16c_concurrent_ap")
    handle2 = backend.submit(contract2.to_backend_projection())
    server.set_status_sequence(handle2.run_id, [("waiting_for_approval", {})])
    server.sse[handle2.run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo concurrent", "preview": "echo concurrent"}),
        ("close",),
    ]
    container2: Dict[str, Any] = {}

    def consume2() -> None:
        for be in backend.events(handle2):
            if be.event_type == "approval.request":
                container2["approval_id"] = be.payload.get("approval_id")

    t2 = threading.Thread(target=consume2, daemon=True)
    t2.start()
    assert _wait_until(lambda: "approval_id" in container2)
    approval_id2 = container2["approval_id"]
    assert broker.resolve(approval_id2, ApprovalDecisionKind.APPROVE_ONCE).ok
    barrier = threading.Barrier(4)
    results: List[Dict[str, Any]] = []

    def racer() -> None:
        barrier.wait()
        results.append(backend.resolve_approval(approval_id2))

    threads = [threading.Thread(target=racer, daemon=True) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=10)
    assert len(results) == 4
    forwarded = [r for r in results if r.get("forwarded") is True]
    noops = [r for r in results if r.get("forwarded") is False]
    assert len(forwarded) == 1, f"并发 resolve 只能一个请求获胜: {results}"
    assert len(noops) == 3
    assert forwarded[0]["resolved"] == 1 and forwarded[0]["choice"] == "once"
    assert len(server.approval_requests) == 1, \
        f"同 approval 并发 resolve 只能有一个 Hermes POST: {server.approval_requests}"
    # 409 错误码精确校验：approval_not_pending → typed no-op；其他 409 → 协议错误
    contract3 = _make_contract(contract_id="wc_16c_409_exact")
    handle3 = backend.submit(contract3.to_backend_projection())
    server.set_status_sequence(handle3.run_id, [("waiting_for_approval", {})])
    server.sse[handle3.run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo 409", "preview": "echo 409"}),
        ("close",),
    ]
    container3: Dict[str, Any] = {}

    def consume3() -> None:
        for be in backend.events(handle3):
            if be.event_type == "approval.request":
                container3["approval_id"] = be.payload.get("approval_id")

    t3 = threading.Thread(target=consume3, daemon=True)
    t3.start()
    assert _wait_until(lambda: "approval_id" in container3)
    approval_id3 = container3["approval_id"]
    assert broker.resolve(approval_id3, ApprovalDecisionKind.APPROVE_ONCE).ok
    server.approval_response[handle3.run_id] = (
        409, {"error": {"message": "no pending", "code": "approval_not_pending"}})
    result409 = backend.resolve_approval(approval_id3)
    assert result409["resolved"] == 0 and result409["forwarded"] is True
    server.approval_response[handle3.run_id] = (
        409, {"error": {"message": "no session", "code": "approval_not_active"}})
    contract4 = _make_contract(contract_id="wc_16c_409_wrong")
    handle4 = backend.submit(contract4.to_backend_projection())
    server.set_status_sequence(handle4.run_id, [("waiting_for_approval", {})])
    server.sse[handle4.run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo 409b", "preview": "echo 409b"}),
        ("close",),
    ]
    container4: Dict[str, Any] = {}

    def consume4() -> None:
        for be in backend.events(handle4):
            if be.event_type == "approval.request":
                container4["approval_id"] = be.payload.get("approval_id")

    t4 = threading.Thread(target=consume4, daemon=True)
    t4.start()
    assert _wait_until(lambda: "approval_id" in container4)
    assert broker.resolve(container4["approval_id"], ApprovalDecisionKind.APPROVE_ONCE).ok
    server.approval_response[handle4.run_id] = (
        409, {"error": {"message": "no session", "code": "approval_not_active"}})
    with pytest.raises(HermesProtocolError, match="approval_not_pending"):
        backend.resolve_approval(container4["approval_id"])
    # resolved != 1 的 200 绝不虚报成功
    contract5 = _make_contract(contract_id="wc_16c_resolved0")
    handle5 = backend.submit(contract5.to_backend_projection())
    server.set_status_sequence(handle5.run_id, [("waiting_for_approval", {})])
    server.sse[handle5.run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo r0", "preview": "echo r0"}),
        ("close",),
    ]
    container5: Dict[str, Any] = {}

    def consume5() -> None:
        for be in backend.events(handle5):
            if be.event_type == "approval.request":
                container5["approval_id"] = be.payload.get("approval_id")

    t5 = threading.Thread(target=consume5, daemon=True)
    t5.start()
    assert _wait_until(lambda: "approval_id" in container5)
    assert broker.resolve(container5["approval_id"], ApprovalDecisionKind.APPROVE_ONCE).ok
    server.approval_response[handle5.run_id] = (
        200, {"object": "hermes.run.approval_response", "run_id": handle5.run_id,
              "choice": "once", "resolved": 0})
    with pytest.raises(HermesProtocolError, match="resolved"):
        backend.resolve_approval(container5["approval_id"])
    for th in (t, t2, t3, t4, t5):
        th.join(timeout=5)
    backend.close()


# --------------------------------------------------------------- R3: submit 原子幂等
def test_28_reviewer_concurrent_duplicate_submit_single_post(server):
    """R3-locked：两线程提交同一 contract → 服务器只收到一个 POST，两者获得同一结果；
    首次 submit 结果不确定后绝不自动重提。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    server.submit_delay = 0.4   # 拉开并发窗口
    barrier = threading.Barrier(2)
    results: List[Any] = []

    def submitter() -> None:
        barrier.wait()
        try:
            results.append(("ok", backend.submit(contract.to_backend_projection())))
        except Exception as exc:   # noqa: BLE001
            results.append(("err", exc))

    threads = [threading.Thread(target=submitter, daemon=True) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=15)
    server.submit_delay = 0.0
    assert len(results) == 2
    outcomes = {kind for kind, _ in results}
    assert outcomes == {"ok"}, f"并发同契约必须同结果: {results}"
    run_ids = {r.run_id for _, r in results}
    assert len(run_ids) == 1, f"两者必须获得同一 run handle: {results}"
    posts = server.requests_to("/v1/runs", method="POST")
    assert len(posts) == 1, f"服务器只能收到一个 POST: {len(posts)}"
    # 结果不确定（连接被切断）→ reservation 中毒：同 contract 后续 submit 一律拒绝，
    # 绝不自动重提（始终只有第一个 POST）
    contract_b = _make_contract(contract_id="wc_16c_ambiguous")
    backend_b = _make_backend(server, contract=contract_b)
    server.drop_next_submit = True
    with pytest.raises(HermesTransportError, match="不确定"):
        backend_b.submit(contract_b.to_backend_projection())
    n_posts = len(server.requests_to("/v1/runs", method="POST"))
    with pytest.raises(HermesTransportError, match="不自动重提"):
        backend_b.submit(contract_b.to_backend_projection())
    with pytest.raises(HermesTransportError, match="不自动重提"):
        backend_b.submit(contract_b.to_backend_projection())
    assert len(server.requests_to("/v1/runs", method="POST")) == n_posts, \
        "结果不确定后绝无第二次 POST"
    backend.close()
    backend_b.close()


def test_29_reviewer_concurrency_and_ledger_hard_capacity(server):
    """R3-locked：max_concurrent_runs 真实执行（终态交付才释放槽位）；
    contract/run/approval 账本硬容量 fail-closed，不淘汰、不诱导重执行。"""
    contract_a = _make_contract(contract_id="wc_16c_cap_a")
    backend = _make_backend(server, contract=contract_a,
                            max_concurrent_runs=1, max_tracked_contracts=2,
                            max_tracked_runs=8)
    handle_a = backend.submit(contract_a.to_backend_projection())
    # 并发槽满：第二个不同契约 submit fail-closed（reservation 释放，不占账本）
    contract_b = _make_contract(contract_id="wc_16c_cap_b")
    with pytest.raises(BackendScopeViolation, match="max_concurrent_runs"):
        backend.submit(contract_b.to_backend_projection())
    # A 权威终态交付 → 槽位释放 → B 可提交
    server.set_status_sequence(handle_a.run_id, [("running", {})])
    server.sse[handle_a.run_id] = [
        ("frame", {"event": "run.completed", "output": "OK",
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}),
        ("close",),
    ]
    list(backend.events(handle_a))
    handle_b = backend.submit(contract_b.to_backend_projection())
    server.set_status_sequence(handle_b.run_id, [("running", {})])
    server.sse[handle_b.run_id] = [
        ("frame", {"event": "run.completed", "output": "OK",
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}),
        ("close",),
    ]
    list(backend.events(handle_b))
    # contract 账本硬容量（=2）：第三个契约 fail-closed；不淘汰 → A 幂等重放仍返回
    # 同一 handle 且零新 POST
    contract_c = _make_contract(contract_id="wc_16c_cap_c")
    with pytest.raises(BackendScopeViolation, match="硬容量"):
        backend.submit(contract_c.to_backend_projection())
    assert backend.submit(contract_a.to_backend_projection()) == handle_a
    assert len(server.requests_to("/v1/runs", method="POST")) == 2, \
        "账本不淘汰：重放零新 POST"
    # run 账本硬容量（Patch 2：POST **前**原子预留）：容量满 → 第二契约零 POST、
    # 确定性 pre-POST 拒绝（非中毒，重试同样零 POST 拒绝）
    backend_r = _make_backend(server, contract=_make_contract(contract_id="wc_16c_cap_r"),
                              max_concurrent_runs=4, max_tracked_runs=1)
    contract_r1 = _make_contract(contract_id="wc_16c_cap_r")
    contract_r2 = _make_contract(contract_id="wc_16c_cap_r2")
    backend_r.submit(contract_r1.to_backend_projection())
    n_posts_r = len(server.requests_to("/v1/runs", method="POST"))
    with pytest.raises(BackendScopeViolation, match="硬容量"):
        backend_r.submit(contract_r2.to_backend_projection())
    with pytest.raises(BackendScopeViolation, match="硬容量"):
        backend_r.submit(contract_r2.to_backend_projection())
    assert len(server.requests_to("/v1/runs", method="POST")) == n_posts_r, \
        "run 账本容量满 → POST 前预留失败 → 绝不发出第二个 POST"
    backend_r.close()
    # approval 账本硬容量：满容量后新审批 fail-closed 自动 deny，不建立 16D 请求
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    backend_p = _make_backend(server, broker=broker,
                              contract=_make_contract(contract_id="wc_16c_cap_p"),
                              max_concurrent_runs=4, max_tracked_approvals=1)
    contract_p = _make_contract(contract_id="wc_16c_cap_p")
    handle_p = backend_p.submit(contract_p.to_backend_projection())
    server.set_status_sequence(handle_p.run_id, [("running", {}),
                                                 ("completed", {"output": "OK"})])
    server.sse[handle_p.run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo one", "preview": "echo one"}),
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "echo two", "preview": "echo two"}),
        ("frame", {"event": "run.completed", "output": "OK",
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}),
        ("close",),
    ]
    approval_ids = [be.payload["approval_id"] for be in backend_p.events(handle_p)
                    if be.event_type == "approval.request"]
    assert len(approval_ids) == 1, "容量满后不得建立第二个 16D 请求"
    denies = [body for _, body in server.approval_requests
              if body.get("choice") == "deny"]
    assert len(denies) == 1, "容量满的新审批必须 fail-closed 自动 deny"
    backend.close()
    backend_p.close()


# --------------------------------------------------------------- R4: HTTP/status 身份封闭
def test_30_reviewer_status_wrong_run_id_never_terminal(server):
    """R4-locked：status/reconcile 返回的 run_id 缺失或冲突 → 绝不产生终态；
    身份冲突可观察（protocol.error），窗口耗尽按 UNKNOWN 收口，零重复 submit。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract,
                            reconnect_poll_budget_seconds=0.3)
    handle = backend.submit(contract.to_backend_projection())
    run_id = handle.run_id
    # run_id 冲突的"completed"必须被拒绝
    server.set_status_sequence(run_id, [("running", {}),
                                        ("completed", {"run_id": "run_other",
                                                       "output": "EVIL"})])
    server.sse[run_id] = [("close",)]   # SSE 立即断线 → reconcile
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    kinds = _kinds(records)
    assert "run.completed" not in kinds, f"错 run_id 的 completed 不得终态: {kinds}"
    assert "status_identity_conflict" in [be.payload.get("reason")
                                          for be, _, _ in records
                                          if be.event_type == "protocol.error"]
    assert "transport.disconnected" in kinds
    assert reducer.view.primary is WorkExecutionState.UNKNOWN
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    # run_id 缺失同样不得终态
    contract2 = _make_contract(contract_id="wc_16c_missing_rid")
    backend2 = _make_backend(server, contract=contract2,
                             reconnect_poll_budget_seconds=0.3)
    handle2 = backend2.submit(contract2.to_backend_projection())
    server.set_status_sequence(handle2.run_id,
                               [("completed", {"run_id": None, "output": "EVIL"})])
    server.sse[handle2.run_id] = [("close",)]
    records2, reducer2 = _drain_events(backend2, handle2, "wc_16c_missing_rid")
    assert "run.completed" not in _kinds(records2)
    assert reducer2.view.primary is WorkExecutionState.UNKNOWN
    backend.close()
    backend2.close()


def test_31_reviewer_json_content_type_and_exact_error_codes(server):
    """R4-locked：text/plain JSON 拒绝；404/409 特殊路径必须验证真实错误码；
    状态词表外/身份形状损坏绝不折算终态。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    # text/plain 承载合法 JSON 的 202 → 协议错误（且结果不确定 → 契约中毒防重提）
    server.submit_raw = (202, "text/plain",
                         json.dumps({"run_id": "run_rawtext",
                                     "status": "started"}).encode("utf-8"))
    bad_ct = _make_contract(contract_id="wc_16c_textplain")
    with pytest.raises(HermesProtocolError, match="application/json"):
        backend.submit(bad_ct.to_backend_projection())
    with pytest.raises(HermesTransportError, match="不自动重提"):
        backend.submit(bad_ct.to_backend_projection())
    # reconcile 404 错误码不符 → 不按 swept 吞掉（继续轮询至预算耗尽）
    contract2 = _make_contract(contract_id="wc_16c_404code")
    backend2 = _make_backend(server, contract=contract2,
                             reconnect_poll_budget_seconds=0.25)
    handle2 = backend2.submit(contract2.to_backend_projection())
    server.route_override["status"] = (404, {"error": {"message": "gone",
                                                       "code": "nope"}})
    server.sse[handle2.run_id] = [("close",)]
    records2, reducer2 = _drain_events(backend2, handle2, "wc_16c_404code")
    swept = [be for be, _, _ in records2
             if be.event_type == "transport.disconnected"
             and be.payload.get("reason") == "run_record_swept"]
    assert not swept, "错误码不符的 404 绝不按 run_record_swept 吞掉"
    wrong_code = [be.payload.get("reason") for be, _, _ in records2
                  if be.event_type == "protocol.error"]
    assert "status_404_wrong_code" in wrong_code
    assert reducer2.view.primary is WorkExecutionState.UNKNOWN
    # 状态词表外的 status → 绝不终态
    server.route_override.clear()
    contract3 = _make_contract(contract_id="wc_16c_badword")
    backend3 = _make_backend(server, contract=contract3,
                             reconnect_poll_budget_seconds=0.25)
    handle3 = backend3.submit(contract3.to_backend_projection())
    server.set_status_sequence(handle3.run_id, [("exploded", {"output": "EVIL"})])
    server.sse[handle3.run_id] = [("close",)]
    records3, reducer3 = _drain_events(backend3, handle3, "wc_16c_badword")
    assert "run.exploded" not in _kinds(records3)
    assert "run.completed" not in _kinds(records3)
    assert reducer3.view.primary is WorkExecutionState.UNKNOWN
    backend.close()
    backend2.close()
    backend3.close()


# --------------------------------------------------------------- R5: SSE parser
def test_32_reviewer_oversize_suffix_never_revives_terminal(server):
    """R5-locked：事件超限（原始 UTF-8 bytes 计数）→ discard-until-blank；
    同一超限事件的后续 data 行绝不重新解释/复活为 terminal；流后续合法帧继续交付。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract, max_event_bytes=1024)
    handle = backend.submit(contract.to_backend_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {})])
    evil1 = json.dumps({"event": "run.completed", "output": "EVIL-1"}).encode()
    evil2 = json.dumps({"event": "run.completed", "output": "EVIL-2"}).encode()
    ok_failed = json.dumps({"event": "run.failed", "error": "authoritative"}).encode()
    server.sse[run_id] = [
        # 一个事件 = 连续 data 行直到空行：line1(1000B) + line2 超过 1024B 事件上限
        ("raw", b"data: " + b"A" * 1000 + b"\n"),
        ("raw", b"data: " + evil1 + b"\n"),
        # 超限事件的"后半段"：不得复活为新事件/terminal
        ("raw", b"data: " + evil2 + b"\n"),
        ("raw", b"\n"),   # 空行：discard 状态结束
        ("raw", b"data: " + ok_failed + b"\n\n"),
        ("close",),
    ]
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    kinds = _kinds(records)
    assert kinds.count("run.completed") == 0, \
        f"超限事件后半段绝不复活为 terminal: {kinds}"
    over = [be for be, _, _ in records
            if be.event_type == "protocol.error"
            and be.payload.get("reason") == "sse_event_over_limit"]
    assert over, "必须报告 sse_event_over_limit"
    assert kinds.count("run.failed") == 1, "空行后的后续合法帧继续交付"
    assert reducer.view.primary is WorkExecutionState.FAILED
    backend.close()


def test_33_reviewer_invalid_utf8_never_business_event(server):
    """R5-locked：非法 UTF-8 字节 → protocol.error，且不得形成业务/终态事件；
    权威终态只来自 status reconcile。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {}), ("completed", {"output": "OK"})])
    server.sse[run_id] = [
        ("raw", b"data: {\"event\": \"tool.started\", \"tool\": \"t\xff\xfebad\"}\n\n"),
        ("raw", b"data: {\"event\": \"run.completed\", \"output\": \"EVIL\"}\n\n"),
        ("close",),
    ]
    records, reducer = _drain_events(backend, handle, CONTRACT_ID)
    kinds = _kinds(records)
    assert "tool.started" not in kinds, "非法 UTF-8 不得形成业务事件"
    assert "run.completed" not in kinds or \
        all(be.payload.get("output") == "OK" for be, _, _ in records
            if be.event_type == "run.completed"), "EVIL 帧不得成为终态 payload"
    invalid = [be for be, _, _ in records
               if be.event_type == "protocol.error"
               and be.payload.get("reason") == "sse_invalid_utf8"]
    assert invalid, "必须报告 sse_invalid_utf8"
    completed = [be for be, _, _ in records if be.event_type == "run.completed"]
    assert len(completed) == 1 and completed[0].payload.get("output") == "OK", \
        "终态只来自权威 status reconcile"
    assert reducer.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    backend.close()


# --------------------------------------------------------------- R4: 裸 key 零泄漏
def test_34_reviewer_bare_api_key_echo_zero_leak(server):
    """裸 API key 回显：先按精确 key 值脱敏、再做秘密形态脱敏——服务端把 key 原样
    放进错误消息也不得进入异常文本。"""
    contract = _make_contract()
    backend = _make_backend(server, contract=contract)
    # 形态脱敏抓不到的裸值回显（无 key=/token= 形态）
    server.submit_response = (401, {"error": {"message":
                                              f"invalid credential {server.api_key} rejected"}})
    with pytest.raises(HermesTransportError) as exc_info:
        backend.submit(_make_contract(contract_id="wc_16c_barekey")
                       .to_backend_projection())
    assert server.api_key not in str(exc_info.value), \
        f"裸 key 值泄漏进异常: {exc_info.value}"
    assert "[REDACTED]" in str(exc_info.value)
    # 秘密形态回显同样零泄漏
    server.submit_response = (500, {"error": {"message":
                                              f"boom api_key={server.api_key} internal"}})
    with pytest.raises(HermesTransportError) as exc_info2:
        backend.submit(_make_contract(contract_id="wc_16c_formkey")
                       .to_backend_projection())
    assert server.api_key not in str(exc_info2.value)
    backend.close()


# --------------------------------------------------------------- R6: lying capabilities
def test_35_reviewer_lying_capabilities_probe_unhealthy(server):
    """R6-locked：required feature 只广告但实际 endpoint 缺失（错误码不符的 404）、
    认证异常或形状矛盾 → probe 必须 unhealthy；probe 全程无副作用（零真实 run）。"""
    # events 端点缺失（404 但错误码不是 run_not_found = 路由不存在）
    server.route_override["events"] = (404, {"error": {"message": "no route",
                                                       "code": "not_found"}})
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "run_events" in h.reason
    backend.close()
    # approval 端点缺失
    server.route_override = {"approval": (404, {"error": {"message": "no route",
                                                          "code": "not_found"}})}
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "run_approval" in h.reason
    backend.close()
    # stop 端点缺失
    server.route_override = {"stop": (404, {"error": {"message": "no route",
                                                      "code": "not_found"}})}
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "run_stop" in h.reason
    backend.close()
    # status 端点形状矛盾（200 而非 404 → 广告与实际矛盾）
    server.route_override = {"status": (200, {"object": "hermes.run", "status": "queued"})}
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "run_status" in h.reason
    backend.close()
    # events 端点认证异常（401）
    server.route_override = {"events": (401, {"error": {"code": "gateway_auth_failed"}})}
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy and "auth_rejected" in h.reason
    backend.close()
    # 副作用封闭：probe 全程零 POST /v1/runs、零真实 run 注册
    assert not server.requests_to("/v1/runs", method="POST")
    assert all(rid.startswith("prb_") for rid in server.runs) or not server.runs


# =================================================================================
# ================================ Reviewer Patch 2 专项 ============================
# =================================================================================

# --------------------------------------------------------------- P2-1: submit 前置 probe 门
def test_36_reviewer_unprobed_submit_zero_post(server):
    """P2-locked：未 probe（无任何 probe 事实）submit → 类型化拒绝、零 POST
    （submit 不自动补 probe——新鲜事实由调用方主动建立）。"""
    contract = _make_contract(contract_id="wc_16c_noprobe")
    backend = _make_backend(server, contract=contract, preprobe=False)
    assert backend.profile_tools_snapshot == ()   # 未 probe → 无快照
    with pytest.raises(HermesProtocolError, match="probe"):
        backend.submit(contract.to_backend_projection())
    assert not server.requests_to("/v1/runs", method="POST"), "未 probe 绝不 POST"
    # probe 后同一 submit 主路径恢复（1 次 POST）
    assert backend.probe().healthy
    assert backend.submit(contract.to_backend_projection()).run_id.startswith("run_")
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    backend.close()


def test_37_reviewer_expired_probe_submit_zero_post(server):
    """P2-locked：probe 过期（超出 TTL）submit → 类型化拒绝、零 POST
    （不自动补 probe；过期事实不可用作放行依据）。"""
    contract = _make_contract(contract_id="wc_16c_probeexpire")
    backend = _make_backend(server, contract=contract, preprobe=True,
                            probe_ttl_seconds=0.1)
    time.sleep(0.3)
    with pytest.raises(HermesProtocolError, match="过期"):
        backend.submit(contract.to_backend_projection())
    assert not server.requests_to("/v1/runs", method="POST"), "probe 过期绝不 POST"
    backend.close()


# --------------------------------------------------------------- P2-2: 工具面精确封闭
def test_38_reviewer_toolset_surface_exact_match(server):
    """P2-locked：probe 工具面与 expected_profile_tools **精确相等**——多一个、
    少一个、未知工具、坏类型工具、platform != api_server 全部 unhealthy；
    精确相等 → healthy 且快照 == expected。"""
    good = server.toolsets
    base_list = [dict(e) for e in good[1]["data"]]

    def variant(platform=None, mutate=None):
        data = [dict(e, tools=list(e["tools"])) for e in base_list]
        if mutate is not None:
            mutate(data)
        return (200, {"object": "list", "platform": platform or "api_server",
                      "data": data})

    cases = [
        # 多一个（额外 enabled 工具集 web_fetch 进入工具面）
        ("多一个 enabled 工具",
         variant(mutate=lambda d: d.__setitem__(
             2, {**d[2], "enabled": True, "configured": True})),
         "toolset_surface_mismatch"),
        # 少一个（expected 内的 filesystem 工具集被禁用）
        ("少一个 enabled 工具",
         variant(mutate=lambda d: d.__setitem__(1, {**d[1], "enabled": False})),
         "toolset_surface_mismatch"),
        # 未知工具（不在构造期封闭映射/expected 集内）
        ("未知工具",
         variant(mutate=lambda d: d[0]["tools"].append("mystery_tool")),
         "toolset_surface_mismatch"),
        # 坏类型工具（enabled 工具集内非 str 工具名）
        ("坏类型工具",
         variant(mutate=lambda d: d[0]["tools"].insert(0, 123)),
         "toolsets_tool_invalid"),
        # platform 不是 api_server（工具面证据不属于本平台）
        ("platform 越界", variant(platform="gateway"),
         "toolsets_platform_contradiction"),
    ]
    for label, toolsets, reason in cases:
        server.toolsets = toolsets
        backend = _make_backend(server, preprobe=True)
        h = backend.probe()
        assert not h.healthy, f"{label} 必须 unhealthy: {h.reason}"
        assert reason in h.reason, f"{label} 期望 {reason}，得到 {h.reason}"
        backend.close()
    # 正例：恢复默认（精确相等 + 全部合法）→ healthy，快照精确等于 expected
    server.toolsets = good
    backend = _make_backend(server, preprobe=True)
    h = backend.probe()
    assert h.healthy, f"精确相等 + 全部合法必须 healthy: {h.reason}"
    assert backend.profile_tools_snapshot == DEFAULT_PROFILE_TOOLS
    assert backend.expected_profile_tools == DEFAULT_PROFILE_TOOLS
    backend.close()


def test_47_reviewer_expected_profile_tools_construction_closure(server):
    """P2-locked：expected_profile_tools 构造期封闭——空集/重复/非 str/无归属工具/
    归属 capability 集 != envelope 全部构造期拒绝；contract_authorizer 缺失拒绝。"""
    with pytest.raises(HermesConfigurationError, match="非空"):
        _make_backend(server, expected_profile_tools=())
    with pytest.raises(HermesConfigurationError, match="重复"):
        _make_backend(server, expected_profile_tools=("terminal", "terminal"))
    with pytest.raises(HermesConfigurationError, match="非空 str"):
        _make_backend(server, expected_profile_tools=("terminal", 123))
    with pytest.raises(HermesConfigurationError, match="无 tool→capability 归属"):
        _make_backend(server, expected_profile_tools=("terminal", "god_tool"))
    # 归属集 {cap.filesystem} != envelope {cap.filesystem, cap.other} → 拒绝
    with pytest.raises(HermesConfigurationError, match="封闭一致"):
        _make_backend(server, expected_profile_tools=("terminal",),
                      capability_ids=("cap.filesystem", "cap.other"))
    # authorizer 非 callable（含 None）→ 构造拒绝（integrity hash 不声明授权真实性）
    with pytest.raises(HermesConfigurationError, match="contract_authorizer"):
        HermesExecutionBackend(
            base_url=server.base_url, api_key=server.api_key,
            approval_broker=ApprovalBroker(),
            expected_profile_identity=PROFILE_ID,
            expected_profile_tools=DEFAULT_PROFILE_TOOLS,
            tool_capability_map=dict(DEFAULT_TOOL_MAP),
            contract_authorizer=None,
            capability_ids=("cap.filesystem",))


# --------------------------------------------------------------- P2-3: 撤销 vs 远端边界
def test_39_reviewer_revocation_between_decision_and_post(server, monkeypatch):
    """P2-locked（Patch 3 升级为 Gate 边界）：撤销发生在 16D decision 与 Hermes POST
    之间 → 发送边界的 gate.consume_permit 原子复核 REVOKED → **绝不发送 once**
    （fail-closed deny）；契约无注入 Gate 同样绝不 once（零 16D 请求）。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_revoke_window")
    contract_ni = _make_contract(contract_id="wc_16c_revoke_noissuer")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract),
                            max_concurrent_runs=4)

    def open_approval(c: WorkContract) -> str:
        handle = backend.submit(c.to_backend_projection())
        server.set_status_sequence(handle.run_id, [("waiting_for_approval", {})])
        server.sse[handle.run_id] = [
            ("frame", {"event": "approval.request", "tool": "terminal",
                       "command": "rm -rf target", "preview": "rm -rf target"}),
            ("close",),
        ]
        box: Dict[str, Any] = {}

        def consume() -> None:
            for be in backend.events(handle):
                if be.event_type == "approval.request":
                    box["approval_id"] = be.payload["approval_id"]

        t = threading.Thread(target=consume, daemon=True)
        t.start()
        assert _wait_until(lambda: "approval_id" in box)
        t.join(timeout=10)
        assert not t.is_alive()
        return box["approval_id"]

    # (a) 撤销精确落在 decision（ALLOW 已生效）与 permit 消费边界之间：
    #     Gate ALLOW 后、gate.consume_permit 入口注入撤销 → 真实 consume 复核拒绝
    approval_id = open_approval(contract)
    assert broker.resolve(approval_id, ApprovalDecisionKind.APPROVE_ONCE).ok
    assert broker.state_of(approval_id) is ApprovalState.APPROVED_ONCE
    real_consume = broker.consume_permit

    def revoke_inside_boundary(permit, *, tool, capability, args):
        assert broker.revoke(permit.approval_id).ok, "边界内撤销必须成功落入窗口"
        return real_consume(permit, tool=tool, capability=capability, args=args)

    monkeypatch.setattr(broker, "consume_permit", revoke_inside_boundary)
    result = backend.resolve_approval(approval_id)
    monkeypatch.undo()
    assert result["choice"] == "deny", "decision 与 POST 之间撤销 → 绝不 once"
    assert result.get("boundary") == "boundary_permit_denied"
    assert result.get("consumed") is not True
    assert not broker.is_consumed(approval_id)
    assert server.approval_requests[-1] == (
        backend._approval_ops[approval_id].run_id, {"choice": "deny"}), \
        "Hermes 只能收到 deny"
    # (b) 契约无注入 Gate：approval.request 自动 deny，零 16D 请求、零 once
    n_requested = len([e for e in broker.events if e.etype == "approval.requested"])
    handle_ni = backend.submit(contract_ni.to_backend_projection())
    server.set_status_sequence(handle_ni.run_id, [("running", {}),
                                                  ("completed", {"output": "OK"})])
    server.sse[handle_ni.run_id] = [
        ("frame", {"event": "approval.request", "tool": "terminal",
                   "command": "rm -rf target", "preview": "rm -rf target"}),
        ("frame", {"event": "run.completed", "output": "OK",
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}),
        ("close",),
    ]
    kinds_ni = [be.event_type for be in backend.events(handle_ni)]
    assert "approval.request" not in kinds_ni, "无 Gate 的契约不得建立审批记录"
    assert len([e for e in broker.events if e.etype == "approval.requested"]) \
        == n_requested, "零 16D 请求"
    assert all(body.get("choice") == "deny" for _, body in server.approval_requests), \
        "全程绝无 once"
    backend.close()


# --------------------------------------------------------------- P2-4: run 账本原子容量
def test_40_reviewer_run_ledger_capacity_reserved_before_post(server):
    """P2-locked：run ledger cap=1 时第二次提交 → POST 前预留失败 → 零 POST。"""
    backend = _make_backend(server, max_tracked_runs=1, max_concurrent_runs=4)
    c1 = _make_contract(contract_id="wc_16c_runcap1_a")
    backend.submit(c1.to_backend_projection())
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    c2 = _make_contract(contract_id="wc_16c_runcap1_b")
    with pytest.raises(BackendScopeViolation, match="硬容量"):
        backend.submit(c2.to_backend_projection())
    assert len(server.requests_to("/v1/runs", method="POST")) == 1, \
        "容量满 → 预留在 POST 前失败 → 第二次提交零 POST"
    backend.close()


def test_41_reviewer_run_id_collision_never_overwrites(server):
    """P2-locked：两 contract 返回同一 run_id → 不覆盖（原 owner/槽位/事件归属
    不变）；本契约 typed conflict + reservation 中毒不重提。"""
    backend = _make_backend(server, max_concurrent_runs=4)
    cA = _make_contract(contract_id="wc_16c_collide_a")
    handle_a = backend.submit(cA.to_backend_projection())
    # B 的 202 返回 A 的 run_id（服务器侧 run_id 复用/异常）
    server.submit_response = (202, {"run_id": handle_a.run_id, "status": "started"})
    cB = _make_contract(contract_id="wc_16c_collide_b")
    with pytest.raises(HermesProtocolError, match="已属于另一契约"):
        backend.submit(cB.to_backend_projection())
    # 原 owner 未被覆盖：A 幂等重放同 handle；B 中毒不重提
    assert backend.submit(cA.to_backend_projection()) == handle_a
    with pytest.raises(HermesTransportError, match="不自动重提"):
        backend.submit(cB.to_backend_projection())
    assert backend._runs[handle_a.run_id].contract_id == cA.contract_id
    server.set_status_sequence(handle_a.run_id,
                               [("running", {}), ("completed", {"output": "OK"})])
    server.sse[handle_a.run_id] = [("frame", {"event": "run.completed", "output": "OK"}),
                                   ("close",)]
    kinds = [be.event_type for be in backend.events(handle_a)]
    assert "run.completed" in kinds, "原 run 的事件归属不受冲突影响"
    backend.close()


def test_42_reviewer_forged_correlation_rejected(server):
    """P2-locked：伪造 handle.correlation 的 events/stop → 类型化拒绝（零 HTTP）。"""
    contract = _make_contract(contract_id="wc_16c_correlation")
    backend = _make_backend(server, contract=contract)
    handle = backend.submit(contract.to_backend_projection())
    forged = BackendRunHandle(backend_id="hermes", run_id=handle.run_id,
                              correlation="wc_16c_forged")
    n_requests = len(server.requests)
    with pytest.raises(HermesProtocolError, match="correlation"):
        list(backend.events(forged))
    with pytest.raises(HermesProtocolError, match="correlation"):
        backend.stop(forged)
    assert len(server.requests) == n_requests, "correlation 拒绝必须零 HTTP"
    backend.close()


# --------------------------------------------------------------- P2-5: approval 容量原子状态机
def test_43_reviewer_approval_capacity_concurrent_attack(server):
    """P2-locked：cap=1 并发攻击——两线程同时提交不同操作的 approval.request：
    最终索引 ≤ 1；容量失败不遗留第二个可用 16D request；Hermes 只收到 fail-closed
    deny（白盒 _RunRecord/_handle_approval_input 用于确定性并发驱动）。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_apcap_atk")
    backend = _make_backend(server, broker=broker, contract=contract,
                            max_concurrent_runs=4, max_tracked_approvals=1)
    handle = backend.submit(contract.to_backend_projection())
    record = _RunRecord(contract.contract_id, contract.content_hash,
                        tuple(contract.allowed_capabilities), contract=contract)
    frames = [{"event": "approval.request", "tool": "terminal",
               "command": f"echo attack-{i}", "preview": f"echo attack-{i}"}
              for i in range(2)]
    outcomes: List[Tuple[Optional[str], Optional[str]]] = []
    barrier = threading.Barrier(2)
    olock = threading.Lock()

    def attacker(frame: Dict[str, Any]) -> None:
        barrier.wait(timeout=10)
        r = backend._handle_approval_request(handle.run_id, record, dict(frame))
        with olock:
            outcomes.append(r)

    threads = [threading.Thread(target=attacker, args=(f,), daemon=True) for f in frames]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(outcomes) == 2
    approved = [a for a, _r in outcomes if a is not None]
    denied = [r for _a, r in outcomes if r == "approval_ledger_full"]
    assert len(approved) == 1 and len(denied) == 1, \
        f"cap=1 并发攻击：恰好一个入账、一个容量 fail-closed deny: {outcomes}"
    assert len(backend._approval_ops) <= 1, "最终索引必须 <= cap"
    requested = [e for e in broker.events if e.etype == "approval.requested"]
    assert len(requested) == 1, "容量失败不得遗留第二个可用 16D request"
    denies = [body for _, body in server.approval_requests
              if body.get("choice") == "deny"]
    assert len(denies) == 1, "Hermes 只收到 fail-closed deny"
    assert not any(body.get("choice") == "once" for _, body in server.approval_requests)
    backend.close()


def test_44_reviewer_unauthorized_valid_contract_zero_post(server):
    """P2-locked：未经 authorizer 的**合法自哈希** WorkContract（16A 校验全过）→
    submit 前拒绝、零 HTTP；hash 不同/authorizer 异常/返回非 True 同样拒绝。"""
    authorized = _make_contract(contract_id="wc_16c_auth_ok")
    pairs = {(authorized.contract_id, authorized.content_hash)}
    backend = _make_backend(
        server, contract=authorized,
        contract_authorizer=lambda cid, ch: (cid, ch) in pairs)
    # 合法自哈希但未被授权（未知 contract_id）
    intruder = _make_contract(contract_id="wc_16c_auth_intruder")
    with pytest.raises(BackendScopeViolation, match="未经可信组合根"):
        backend.submit(intruder.to_backend_projection())
    # 同 id 不同内容（content_hash 与授权绑定的不同）
    same_id = _make_contract(contract_id="wc_16c_auth_ok", request="换约后的不同内容")
    assert same_id.content_hash != authorized.content_hash
    with pytest.raises(BackendScopeViolation, match="未经可信组合根"):
        backend.submit(same_id.to_backend_projection())
    assert not server.requests_to("/v1/runs", method="POST"), "未授权必须零 HTTP"

    # authorizer 异常 → fail-closed 拒绝（零 HTTP）
    def exploding(cid: str, ch: str) -> bool:
        raise RuntimeError("authorizer 内部错误")

    backend2 = _make_backend(server, contract=authorized, contract_authorizer=exploding)
    with pytest.raises(BackendScopeViolation, match="authorizer 异常"):
        backend2.submit(authorized.to_backend_projection())
    assert not server.requests_to("/v1/runs", method="POST")
    backend2.close()
    # 返回非 True（truthy 字符串）→ 拒绝（必须精确 True）
    backend3 = _make_backend(server, contract=authorized,
                             contract_authorizer=lambda cid, ch: "yes")
    with pytest.raises(BackendScopeViolation, match="未经可信组合根"):
        backend3.submit(authorized.to_backend_projection())
    assert not server.requests_to("/v1/runs", method="POST")
    backend3.close()
    # 被授权的契约主路径恢复（1 次 POST）
    backend.submit(authorized.to_backend_projection())
    assert len(server.requests_to("/v1/runs", method="POST")) == 1
    backend.close()


# --------------------------------------------------------------- P2-7: 精确媒体类型
def test_45_reviewer_exact_media_type_only(server):
    """P2-locked：application/jsonp 与 text/application/json-evil 拒绝；
    非 charset 参数拒绝；application/json; charset=utf-8 合法（正例）。"""
    backend = _make_backend(server)
    body = json.dumps({"run_id": "run_ctype_case", "status": "started"}).encode("utf-8")
    # application/jsonp（前缀仿冒）→ 拒绝
    server.submit_raw = (202, "application/jsonp", body)
    with pytest.raises(HermesProtocolError, match="application/jsonp"):
        backend.submit(_make_contract(contract_id="wc_16c_jsonp")
                       .to_backend_projection())
    # text/application/json-evil（子串仿冒）→ 拒绝
    server.submit_raw = (202, "text/application/json-evil", body)
    with pytest.raises(HermesProtocolError, match="text/application/json-evil"):
        backend.submit(_make_contract(contract_id="wc_16c_jsonevil")
                       .to_backend_projection())
    # 非 charset 参数 → 拒绝
    server.submit_raw = (202, "application/json; boundary=x", body)
    with pytest.raises(HermesProtocolError, match="charset"):
        backend.submit(_make_contract(contract_id="wc_16c_badparam")
                       .to_backend_projection())
    # 注：媒体类型拒绝发生在响应边界（POST 已合法发出，无 run 交付）；三个被拒
    # 契约 reservation 均为 202-形状损坏中毒——绝不自动重提
    for cid in ("wc_16c_jsonp", "wc_16c_jsonevil", "wc_16c_badparam"):
        with pytest.raises((HermesTransportError, HermesProtocolError)):
            backend.submit(_make_contract(contract_id=cid).to_backend_projection())
    # 正例：charset 参数合法 → 202 主路径成功
    server.submit_raw = (202, "application/json; charset=utf-8", body)
    handle = backend.submit(_make_contract(contract_id="wc_16c_charset_ok")
                            .to_backend_projection())
    assert handle.run_id == "run_ctype_case"
    backend.close()


# --------------------------------------------------------------- P2-8: 有界读取
def test_46_reviewer_bounded_error_and_oversize_bodies(server):
    """P2-locked：超限错误响应与错误码响应同样有界——202 超 4MiB body → 立即拒绝
    且超限内容不入异常；500 错误体超 64KiB → 有界标记、内容不入异常。"""
    backend = _make_backend(server)
    marker = b"BOUNDARY-MARKER"
    # (1) 202 + application/json 但 body > 4MiB → 流式有界读取立即拒绝
    huge_ok = (b'{"run_id": "run_big202", "status": "started", "pad": "'
               + marker * (5 * 1024 * 1024 // len(marker)) + b'"}')
    server.submit_raw = (202, "application/json", huge_ok)
    with pytest.raises(HermesProtocolError, match="超过硬上限") as exc_info:
        backend.submit(_make_contract(contract_id="wc_16c_big202")
                       .to_backend_projection())
    assert marker.decode() not in str(exc_info.value), "超限内容绝不入异常"
    assert len(str(exc_info.value)) < 300, "异常文本必须有界"
    # (2) 500 错误体 > 64KiB → 错误码/片段读取有界：内容不入异常，只留标记
    huge_err = marker * (200 * 1024 // len(marker))
    server.submit_raw = (500, "application/json", huge_err)
    with pytest.raises(HermesTransportError) as exc_info2:
        backend.submit(_make_contract(contract_id="wc_16c_big500")
                       .to_backend_projection())
    assert marker.decode() not in str(exc_info2.value), "超限错误体绝不入异常"
    assert len(str(exc_info2.value)) < 300, "异常文本必须有界"
    assert "[error body over limit]" in str(exc_info2.value)
    # (3) 有界内的错误码响应照常提取（正例：小 500 错误体片段可见且脱敏）
    server.submit_raw = (500, "application/json",
                         json.dumps({"error": {"message": "small boom",
                                               "code": "internal"}}).encode())
    with pytest.raises(HermesTransportError, match="small boom"):
        backend.submit(_make_contract(contract_id="wc_16c_small500")
                       .to_backend_projection())


# =================================================================================
# ================================ Reviewer Patch 3 专项 ============================
# =================================================================================

def _drive_approval_frame(server: _FakeHermesServer, backend: HermesExecutionBackend,
                          handle: BackendRunHandle, *, tool: str = "terminal",
                          command: str = "echo OK") -> Tuple[str, threading.Thread]:
    """在已 submit 的 run 上驱动一条 approval.request 帧（随后关流），返回
    (approval_id, consume_thread)——审批经 16D Gate 建立 PENDING 记录后即可决议。"""
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("waiting_for_approval", {})])
    server.sse[run_id] = [
        ("frame", {"event": "approval.request", "tool": tool,
                   "command": command, "preview": command}),
        ("close",),
    ]
    box: Dict[str, Any] = {}

    def consume() -> None:
        for be in backend.events(handle):
            if be.event_type == "approval.request":
                box["approval_id"] = be.payload.get("approval_id")

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    assert _wait_until(lambda: "approval_id" in box), "approval.request 必须建立 16D 审批记录"
    return box["approval_id"], t


def _drain_frames(server: _FakeHermesServer, backend: HermesExecutionBackend,
                  handle: BackendRunHandle, *, tool: str = "terminal",
                  command: str = "echo OK") -> List[Tuple[str, Dict[str, Any]]]:
    """驱动 approval.request 帧 + run.completed（终态收流），返回 (event_type, payload)
    全序列——用于自动 deny（零 approval_id）路径断言。"""
    run_id = handle.run_id
    server.set_status_sequence(run_id, [("running", {}), ("completed", {"output": "OK"})])
    server.sse[run_id] = [
        ("frame", {"event": "approval.request", "tool": tool,
                   "command": command, "preview": command}),
        ("frame", {"event": "run.completed", "output": "OK",
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}),
        ("close",),
    ]
    seen: List[Tuple[str, Dict[str, Any]]] = []
    for be in backend.events(handle):
        seen.append((be.event_type, dict(be.payload)))
    return seen


class _StubChunkResponse:
    """_bounded_body 白盒 stub：只暴露 iter_bytes（单 chunk 超限驱动）。"""

    def __init__(self, chunks: List[bytes]) -> None:
        self.headers = {"content-type": "application/json"}
        self._chunks = list(chunks)

    def iter_bytes(self):
        yield from self._chunks


class _RecordingByteArray(bytearray):
    """记录每次 extend 的 chunk 长度（白盒断言：超限 chunk 绝不进入 extend）。"""

    max_extend_len = 0

    def extend(self, other):  # noqa: D102
        type(self).max_extend_len = max(type(self).max_extend_len, len(other))
        super().extend(other)


# --------------------------------------------------------------- P3-1: PM DENY 零 once
def test_48_reviewer_pm_deny_never_once(server):
    """R3-locked（要求 1/2/9）：permission_decider granted=False → Gate DENY_PERMISSION
    → 自动 deny（零 16D 请求）；用户 APPROVE_ONCE 无从生效，Hermes 只收到 deny。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p3_pmdeny")

    def decider(tool, capability, raw_args, contract_id, run_id):
        return PermissionDecision(False, "pm_deny", Permission.L2_HIGH_RISK)

    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract),
                            permission_decider=decider)
    handle = backend.submit(contract.to_backend_projection())
    seen = _drain_frames(server, backend, handle)
    kinds = [k for k, _p in seen]
    assert "approval.request" not in kinds, "PM DENY 不得建立审批记录（零 approval_id）"
    reasons = [p.get("reason") for k, p in seen if k == "protocol.error"]
    assert "approval_gate_deny_permission" in reasons, f"必须 Gate DENY_PERMISSION: {reasons}"
    assert not [e for e in broker.events if e.etype == "approval.requested"], \
        "PM DENY 零 16D 请求"
    assert server.approval_requests, "Hermes 必须收到 deny 转发"
    assert all(body.get("choice") == "deny" for _, body in server.approval_requests), \
        "Hermes 只收到 deny，绝无 once"
    assert not any(body.get("choice") == "once" for _, body in server.approval_requests)
    # 用户 APPROVE_ONCE 无从生效：没有任何可 resolve 的 approval
    with pytest.raises(HermesProtocolError, match="未知 approval_ref"):
        backend.resolve_approval("apv_fabricated0000")
    backend.close()


# --------------------------------------------------------------- P3-2: PM 降级 零 once
def test_49_reviewer_pm_downgrade_between_decision_and_post(server):
    """R3-locked（要求 5/7）：PM 在 approval（PENDING）后、POST 前由 allow 变 deny →
    resolve 重新取得实时 PermissionDecision 并再次调用同一 Gate.check_step →
    DENY_PERMISSION → 零 once（fail-closed deny；approval 未被消费）。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p3_pmdowngrade")
    state = {"allowed": True}

    def decider(tool, capability, raw_args, contract_id, run_id):
        if state["allowed"]:
            return PermissionDecision(True, "pm_allow", Permission.L2_HIGH_RISK)
        return PermissionDecision(False, "pm_deny", Permission.L2_HIGH_RISK)

    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract),
                            permission_decider=decider)
    handle = backend.submit(contract.to_backend_projection())
    approval_id, t = _drive_approval_frame(server, backend, handle)
    assert broker.state_of(approval_id) is ApprovalState.PENDING
    assert broker.resolve(approval_id, ApprovalDecisionKind.APPROVE_ONCE).ok
    state["allowed"] = False   # PM 在 approval 后、POST 前降级为 deny
    result = backend.resolve_approval(approval_id)
    assert result["choice"] == "deny", "PM 降级 → 零 once（fail-closed deny）"
    assert result.get("boundary") == "boundary_gate_deny_permission"
    assert result.get("consumed") is not True
    assert not broker.is_consumed(approval_id), "PM 降级 → approval 不得被消费"
    assert not any(body.get("choice") == "once" for _, body in server.approval_requests)
    assert all(body.get("choice") == "deny" for _, body in server.approval_requests)
    t.join(timeout=10)
    backend.close()


# --------------------------------------------------------------- P3-3: 源码结构断言
def test_50_reviewer_no_direct_permit_issuer_path():
    """R3-locked（要求 1）：Hermes 源码结构不存在 PermitIssuer.issue 调用 / 直接
    issuer 注册 / create_permit_issuer 路径（AST 级；注释排除在外）；approval 只经
    ApprovalGate.check_step 判定。"""
    import inspect
    tree = ast.parse(inspect.getsource(hermes_module))
    hits: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("issue", "create_permit_issuer"):
            hits.append(f"attribute {node.attr}")
        elif isinstance(node, ast.Name) and node.id == "PermitIssuer":
            hits.append("name PermitIssuer")
        elif isinstance(node, ast.FunctionDef) and node.name == "register_permit_issuer":
            hits.append("def register_permit_issuer")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if "PermitIssuer" in alias.name:
                    hits.append(f"import {alias.name}")
    assert not hits, f"16C 源码不得存在直接 permit 签发/注册路径: {hits}"
    src = ast.unparse(tree)
    assert "ApprovalGate" in src, "approval 判定必须引用 16D ApprovalGate"
    assert "check_step" in src, "approval 必须经 Gate.check_step"
    assert "consume_permit" in src, "once 转发边界必须经 gate.consume_permit"


# --------------------------------------------------------------- P3-4: Gate 契约/hash 不匹配
def test_51_reviewer_gate_contract_hash_mismatch_zero_once(server):
    """R3-locked（要求 4/7）：Gate 内部 issuer 绑定契约 id+hash，submit 的契约同 id
    不同 hash → Gate.check_step DENY_CONTRACT_SCOPE → 零 16D 请求、零 once。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    c_orig = _make_contract(contract_id="wc_16c_p3_hashmm")
    gate = _make_gate(broker, c_orig)
    c_other = _make_contract(contract_id="wc_16c_p3_hashmm", request="换约后的不同内容")
    assert c_other.content_hash != c_orig.content_hash
    backend = _make_backend(server, broker=broker, contract=c_other,
                            approval_gates={"wc_16c_p3_hashmm": gate})
    handle = backend.submit(c_other.to_backend_projection())
    seen = _drain_frames(server, backend, handle)
    kinds = [k for k, _p in seen]
    assert "approval.request" not in kinds, "契约/hash 不匹配不得建立审批记录"
    reasons = [p.get("reason") for k, p in seen if k == "protocol.error"]
    assert any(r and r.startswith("approval_gate_deny_") for r in reasons), \
        f"必须 Gate DENY_CONTRACT_SCOPE: {reasons}"
    assert not [e for e in broker.events if e.etype == "approval.requested"], \
        "契约/hash 不匹配零 16D 请求"
    assert not any(body.get("choice") == "once" for _, body in server.approval_requests), \
        "零 once"
    assert all(body.get("choice") == "deny" for _, body in server.approval_requests)
    backend.close()


# --------------------------------------------------------------- P3-5: Gate ALLOW + 原子消费
def test_52_reviewer_gate_allow_permit_consume_exactly_one_once(server):
    """R3-locked（要求 6/8）：Gate ALLOW + permit + gate.consume_permit 原子消费成功 →
    恰好一个 once；16D approval 真实消费（消费先于 POST）。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p3_allow_once")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract))
    handle = backend.submit(contract.to_backend_projection())
    approval_id, t = _drive_approval_frame(server, backend, handle)
    assert broker.state_of(approval_id) is ApprovalState.PENDING
    assert broker.resolve(approval_id, ApprovalDecisionKind.APPROVE_ONCE).ok
    result = backend.resolve_approval(approval_id)
    assert result["choice"] == "once" and result["resolved"] == 1
    assert result["consumed"] is True, "once 必须先于 POST 完成 Gate 边界原子消费"
    assert result["permit_id"], "结果必须携带边界消费的 permit_id"
    assert broker.is_consumed(approval_id), "Gate ALLOW 路径必须真实消费 16D approval"
    assert server.approval_requests == [(handle.run_id, {"choice": "once"})], \
        f"恰好一个 once: {server.approval_requests}"
    t.join(timeout=10)
    backend.close()


# --------------------------------------------------------------- P3-6: 工具面全等闭合
def test_53_reviewer_extra_tool_map_construction_rejected(server):
    """R3-locked（要求 二）：set(tool_capability_map.keys()) == set(expected_profile_tools)
    构造期强制——多映射/未知映射/空白未规范化名字全部拒绝；少映射同样拒绝。"""
    with pytest.raises(HermesConfigurationError, match="超出 expected_profile_tools"):
        _make_backend(server, tool_capability_map={**DEFAULT_TOOL_MAP, "god_mode": "cap.filesystem"},
                      expected_profile_tools=DEFAULT_PROFILE_TOOLS)
    # 少映射（expected 内工具无归属 → Patch 2 检查保持）
    with pytest.raises(HermesConfigurationError, match="无 tool→capability 归属"):
        _make_backend(server, expected_profile_tools=("terminal", "ghost_tool"))
    # 未知映射（键集与 expected 互有出入）
    with pytest.raises(HermesConfigurationError, match="超出 expected_profile_tools"):
        _make_backend(server, tool_capability_map={**DEFAULT_TOOL_MAP, "mystery_tool": "cap.filesystem"},
                      expected_profile_tools=DEFAULT_PROFILE_TOOLS)
    # 空白/未规范化映射键
    with pytest.raises(HermesConfigurationError, match="未规范化"):
        _make_backend(server, tool_capability_map={**DEFAULT_TOOL_MAP, " terminal": "cap.filesystem"})
    # 空白/未规范化 expected 条目
    with pytest.raises(HermesConfigurationError, match="未规范化"):
        _make_backend(server, expected_profile_tools=("terminal", " write_file "))


# --------------------------------------------------------------- P3-7: expected 外工具零请求
def test_54_reviewer_approval_outside_expected_tools_zero_request(server):
    """R3-locked（要求 二）：approval.request 使用 expected 外工具 → 自动 deny
    （tool ∉ probe 快照 ∩ expected ∩ 映射），零 16D request + Hermes 只收 deny。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p3_outtool")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract))
    handle = backend.submit(contract.to_backend_projection())
    seen = _drain_frames(server, backend, handle, tool="mystery_tool", command="echo x")
    kinds = [k for k, _p in seen]
    assert "approval.request" not in kinds, "expected 外工具零 approval_id"
    reasons = [p.get("reason") for k, p in seen if k == "protocol.error"]
    assert "approval_tool_unmapped" in reasons, f"必须 approval_tool_unmapped: {reasons}"
    assert not [e for e in broker.events if e.etype == "approval.requested"], \
        "expected 外工具零 16D request"
    assert all(body.get("choice") == "deny" for _, body in server.approval_requests), \
        "Hermes 只收到 fail-closed deny"
    assert not any(body.get("choice") == "once" for _, body in server.approval_requests)
    backend.close()


# --------------------------------------------------------------- P3-8: 合法 JSON 前缀 + 读异常
def test_55_reviewer_json_prefix_then_read_error_rejected(server):
    """R3-locked（要求 三.1/三.5）：202 先给合法 JSON 前缀、随后读取中断 → 绝不接受
    前缀（类型化 transport 错误 + reservation 中毒零重提）；前缀内容不入任何结果。"""
    backend = _make_backend(server)
    prefix = b'{"run_id": "run_aborted", "status": "started"}'
    full = prefix + b' "pad": "TAIL"}'
    server.submit_abort_raw = (202, "application/json", prefix, full)
    c = _make_contract(contract_id="wc_16c_p3_prefix_abort")
    with pytest.raises(HermesTransportError, match="读取中断"):
        backend.submit(c.to_backend_projection())
    # 读取中断 → reservation 中毒：同契约绝不自动重提（零第二个 POST）
    n_posts = len(server.requests_to("/v1/runs", method="POST"))
    with pytest.raises(HermesTransportError, match="不自动重提"):
        backend.submit(c.to_backend_projection())
    assert len(server.requests_to("/v1/runs", method="POST")) == n_posts, \
        "前缀不被接受：绝不重试发出第二个 POST"
    backend.close()


# --------------------------------------------------------------- P3-9: 单 chunk 超限 extend 前拒绝
def test_56_reviewer_single_chunk_over_limit_pre_extend_rejected(server, monkeypatch):
    """R3-locked（要求 三.2）：单 chunk 超上限 → 在 extend 前检查余量并拒绝
    （绝不先分配超限内存）；超限内容不入异常文本。"""
    backend = _make_backend(server)
    limit = hermes_module._MAX_JSON_BODY_BYTES
    marker = b"OVER-LIMIT-MARKER"
    chunk = marker * ((limit // len(marker)) + 1)   # 单 chunk > limit
    stub = _StubChunkResponse([chunk])
    # 模块级 bytearray 遮蔽（builtin 不在模块 __dict__ → raising=False）：白盒记录
    # _bounded_body 每次 extend 的 chunk 长度。
    monkeypatch.setattr(hermes_module, "bytearray", _RecordingByteArray, raising=False)
    with pytest.raises(HermesProtocolError, match="超过硬上限") as exc_info:
        backend._bounded_body(stub, limit)
    assert _RecordingByteArray.max_extend_len <= limit, \
        f"超限 chunk 不得在 extend 前被分配（先检查余量再 extend），实际 extend 了 " \
        f"{_RecordingByteArray.max_extend_len} > {limit}"
    assert marker.decode() not in str(exc_info.value), "超限内容绝不入异常"
    assert len(str(exc_info.value)) < 300, "异常文本必须有界"
    backend.close()


# --------------------------------------------------------------- P3-10: text/plain 错误码拒绝
def test_57_reviewer_textplain_error_codes_rejected(server):
    """R3-locked（要求 三.3/三.4）：text/plain 承载的 run_not_found / approval_not_pending
    不得当作已知错误码——probe 握手 404 text/plain → unhealthy；approval 409 text/plain →
    协议错误（非 no-op）。"""
    # (a) probe：404 text/plain run_not_found → 错误码不可提取 → 握手矛盾 unhealthy
    server.route_override_raw["status"] = (
        404, "text/plain", b'{"error": {"code": "run_not_found"}}')
    backend = _make_backend(server)
    h = backend.probe()
    assert not h.healthy, f"text/plain 的 run_not_found 不得当作已知错误码: {h.reason}"
    assert "run_status_handshake_contradiction" in h.reason
    backend.close()
    server.route_override_raw.clear()
    # (b) approval 409 text/plain approval_not_pending → 协议错误（绝不当作 no-op）
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p3_txt409")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract))
    handle = backend.submit(contract.to_backend_projection())
    approval_id, t = _drive_approval_frame(server, backend, handle)
    assert broker.resolve(approval_id, ApprovalDecisionKind.APPROVE_ONCE).ok
    server.route_override_raw["approval"] = (
        409, "text/plain", b'{"error": {"code": "approval_not_pending"}}')
    with pytest.raises(HermesProtocolError, match="approval_not_pending"):
        backend.resolve_approval(approval_id)
    t.join(timeout=10)
    backend.close()


# --------------------------------------------------------------- P3-11: application/json 无回归
def test_58_reviewer_application_json_error_codes_no_regression(server):
    """R3-locked（要求 三.3）：application/json 正常错误码无回归——probe 四端点 404
    run_not_found 握手 healthy；409 approval_not_pending 精确错误码仍是 typed no-op。"""
    backend = _make_backend(server)
    assert backend.probe().healthy, "application/json 的 run_not_found 握手必须正常"
    backend.close()
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p3_json409")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract))
    handle = backend.submit(contract.to_backend_projection())
    approval_id, t = _drive_approval_frame(server, backend, handle)
    assert broker.resolve(approval_id, ApprovalDecisionKind.APPROVE_ONCE).ok
    server.approval_response[handle.run_id] = (
        409, {"error": {"message": "no pending", "code": "approval_not_pending"}})
    result = backend.resolve_approval(approval_id)
    assert result["resolved"] == 0 and result["forwarded"] is True, \
        "application/json 精确 approval_not_pending 仍为 typed no-op"
    t.join(timeout=10)
    backend.close()


# --------------------------------------------------------------- P3-12: Patch 2 不变式保持
def test_59_reviewer_patch2_invariants_preserved(server):
    """R3-locked（要求 12）：Patch 2 的 run capacity、run_id collision、contract
    authorizer、fresh probe 四组锁定测试保持通过（新 Gate 流程零回归）。"""
    # run capacity：cap=1 第二次提交 → POST 前预留失败 → 零 POST
    backend = _make_backend(server, max_tracked_runs=1, max_concurrent_runs=4)
    backend.submit(_make_contract(contract_id="wc_16c_p3_cap_a").to_backend_projection())
    n_posts = len(server.requests_to("/v1/runs", method="POST"))
    with pytest.raises(BackendScopeViolation, match="硬容量"):
        backend.submit(_make_contract(contract_id="wc_16c_p3_cap_b").to_backend_projection())
    assert len(server.requests_to("/v1/runs", method="POST")) == n_posts, \
        "run 容量满 → 零 POST"
    backend.close()
    # run_id collision：B 的 202 返回 A 的 run_id → 不覆盖 + typed conflict
    backend = _make_backend(server, max_concurrent_runs=4)
    handle_a = backend.submit(
        _make_contract(contract_id="wc_16c_p3_col_a").to_backend_projection())
    server.submit_response = (202, {"run_id": handle_a.run_id, "status": "started"})
    with pytest.raises(HermesProtocolError, match="已属于另一契约"):
        backend.submit(_make_contract(contract_id="wc_16c_p3_col_b").to_backend_projection())
    server.submit_response = (202, {"run_id": "@auto", "status": "started"})
    backend.close()
    # contract authorizer：未知 contract_id → submit 前拒绝、零 HTTP
    backend = _make_backend(server,
                            contract=_make_contract(contract_id="wc_16c_p3_auth_ok"),
                            contract_authorizer=lambda cid, ch: cid == "wc_16c_p3_auth_ok")
    n_posts = len(server.requests_to("/v1/runs", method="POST"))
    with pytest.raises(BackendScopeViolation, match="未经可信组合根"):
        backend.submit(_make_contract(contract_id="wc_16c_p3_auth_bad")
                       .to_backend_projection())
    assert len(server.requests_to("/v1/runs", method="POST")) == n_posts, \
        "未授权契约零 HTTP"
    backend.close()
    # fresh probe：未 probe → 零 POST；probe 过期 → 零 POST
    contract_p = _make_contract(contract_id="wc_16c_p3_probe")
    backend = _make_backend(server, contract=contract_p, preprobe=False)
    with pytest.raises(HermesProtocolError, match="probe"):
        backend.submit(contract_p.to_backend_projection())
    backend.close()
    backend = _make_backend(server, contract=contract_p, probe_ttl_seconds=0.1)
    time.sleep(0.3)
    with pytest.raises(HermesProtocolError, match="过期"):
        backend.submit(contract_p.to_backend_projection())
    backend.close()


# =================================================================================
# ================================ Reviewer Patch 4 专项 ============================
# =================================================================================

def _make_evidence_broker() -> ApprovalBroker:
    """16C Patch 4 专用 broker：owner 线程 + 可信 USER 证据验证器（grant 创建可达）。"""
    return ApprovalBroker(owner_thread_id=threading.get_ident(),
                          user_evidence_verifier=lambda uid, ctx: True)


def _create_session_grant(broker: ApprovalBroker, contract: WorkContract, *,
                          tool_pattern: str = "terminal",
                          capability: str = "cap.filesystem") -> Any:
    """可信组合根（16D 公开 API）：canonical USER 证据 → nonce → session grant
    （绑定 contract_id/hash；workspace = 契约 workspace（内含校验通过）；
    tool_pattern 覆盖指定工具；窗口 1h）。调用契约必须声明非空 workspace 根。"""
    event_id = f"lev_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    issued = broker.now()
    expiry = issued + 3600.0
    ws = contract.workspace_scope
    assert ws.read_roots or ws.write_roots, "测试契约必须声明 workspace 根（grant 拒绝无界）"
    context = EvidenceContext(
        decision="grant", contract_id=contract.contract_id,
        contract_hash=contract.content_hash, capability=capability,
        tool_pattern=tool_pattern,
        workspace_read_roots=tuple(ws.read_roots),
        workspace_write_roots=tuple(ws.write_roots),
        issued_at=issued, expiry=expiry, scope_note="16C patch4 negation")
    nonce = broker.request_user_evidence(event_id, context=context)
    return broker.create_grant(
        user_evidence=nonce, contract_id=contract.contract_id,
        contract_hash=contract.content_hash, capability=capability,
        tool_pattern=tool_pattern, workspace_scope=ws,
        expiry=expiry, issued_at=issued, scope_note="16C patch4 negation")


def _denies_for(server: _FakeHermesServer, run_id: str) -> List[Dict[str, Any]]:
    return [b for rid, b in server.approval_requests
            if rid == run_id and b.get("choice") == "deny"]


def _onces_for(server: _FakeHermesServer, run_id: str) -> List[Dict[str, Any]]:
    return [b for rid, b in server.approval_requests
            if rid == run_id and b.get("choice") == "once"]


def _requested_events(broker: ApprovalBroker) -> List[Any]:
    return [e for e in broker.events if e.etype == "approval.requested"]


# --------------------------------------------------------------- P4-1: 决议不被 grant 升级
def test_60_reviewer_resolution_cannot_be_upgraded_by_later_grant(server):
    """P4-locked（blocker 一）：DENY / TIMEOUT / REVOKED 决议后创建**覆盖同操作的
    合法 session grant**，resolve 仍只能 deny——固定 deny、不触碰 Gate、不签发/
    不消费 permit、零 once；对照组证明 grant 本身真实激活且覆盖（新操作真走
    grant-covered once），排除"grant 无效导致 deny"的假阳性。
    （grant 必须绑定非空 workspace 而 hermes submit 面拒绝路径 scope 契约——
    与 test_43 同构，用白盒 _RunRecord 驱动审批域；run 经 server.register_run
    注册使 deny/once 转发可观察。）"""
    ws = WorkspaceScope(read_roots=("C:/ws/p4",), write_roots=("C:/ws/p4",))

    # (a) DENY 后 grant 升级否证
    contract = _make_contract(contract_id="wc_16c_p4_upg_deny", workspace_scope=ws)
    broker = _make_evidence_broker()
    gate = _make_gate(broker, contract)
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates={contract.contract_id: gate})
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    server.register_run(run_id)
    record = _RunRecord(contract.contract_id, contract.content_hash,
                        tuple(contract.allowed_capabilities), contract=contract)
    frame = {"event": "approval.request", "tool": "terminal",
             "command": "echo deny-me", "preview": "echo deny-me"}
    approval_id, r = backend._handle_approval_request(run_id, record, dict(frame))
    assert approval_id and r is None
    assert broker.resolve(approval_id, ApprovalDecisionKind.DENY).ok
    grant = _create_session_grant(broker, contract)
    assert broker.is_grant_active(grant.grant_id), "前置：grant 必须真实激活"
    result = backend.resolve_approval(approval_id)
    assert result["choice"] == "deny", "DENY 决议不得被后出现的 grant 升级"
    assert result["boundary"].startswith("resolution_not_approvable")
    assert result.get("consumed") is not True, "deny 路径绝不消费 permit"
    assert not broker.is_consumed(approval_id)
    assert len(_onces_for(server, run_id)) == 0, "DENY 升级路径零 once"
    # 对照组：同一 grant 对**新**操作真实覆盖 → grant-covered once（证明 grant
    # 活着且 covering——deny 升级被拦截绝非 grant 无效）
    r2 = backend._handle_approval_request(
        run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo grant-covers", "preview": "echo grant-covers"})
    assert r2 == (None, "approval_covered_by_grant_once")
    assert len(_onces_for(server, run_id)) == 1, "对照组新操作真走 grant once"
    backend.close()

    # (b) TIMEOUT 后 grant 升级否证（gate wait_cap 收窄 → 审批到期 TIMED_OUT）
    contract_t = _make_contract(contract_id="wc_16c_p4_upg_timeout", workspace_scope=ws)
    broker_t = _make_evidence_broker()
    gate_t = _make_gate(broker_t, contract_t, gate_kw={"wait_cap_seconds": 0.05})
    backend_t = _make_backend(server, broker=broker_t, contract=contract_t,
                              approval_gates={contract_t.contract_id: gate_t})
    run_id_t = f"run_{uuid.uuid4().hex[:12]}"
    server.register_run(run_id_t)
    record_t = _RunRecord(contract_t.contract_id, contract_t.content_hash,
                          tuple(contract_t.allowed_capabilities), contract=contract_t)
    ap_t, r_t = backend_t._handle_approval_request(
        run_id_t, record_t,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo timeout-me", "preview": "echo timeout-me"})
    assert ap_t and r_t is None
    time.sleep(0.3)
    assert ap_t in broker_t.sweep_timeouts(), "审批必须真实到期"
    assert broker_t.state_of(ap_t) is ApprovalState.TIMED_OUT
    _create_session_grant(broker_t, contract_t)
    result_t = backend_t.resolve_approval(ap_t)
    assert result_t["choice"] == "deny", "TIMEOUT 决议不得被 grant 升级"
    assert result_t.get("consumed") is not True
    assert len(_onces_for(server, run_id_t)) == 0, "TIMEOUT 升级路径零 once"
    backend_t.close()

    # (c) REVOKED 后 grant 升级否证
    contract_r = _make_contract(contract_id="wc_16c_p4_upg_revoke", workspace_scope=ws)
    broker_r = _make_evidence_broker()
    gate_r = _make_gate(broker_r, contract_r)
    backend_r = _make_backend(server, broker=broker_r, contract=contract_r,
                              approval_gates={contract_r.contract_id: gate_r})
    run_id_r = f"run_{uuid.uuid4().hex[:12]}"
    server.register_run(run_id_r)
    record_r = _RunRecord(contract_r.contract_id, contract_r.content_hash,
                          tuple(contract_r.allowed_capabilities), contract=contract_r)
    ap_r, r_r = backend_r._handle_approval_request(
        run_id_r, record_r,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo revoke-me", "preview": "echo revoke-me"})
    assert ap_r and r_r is None
    assert broker_r.revoke(ap_r, reason="用户撤销").ok
    _create_session_grant(broker_r, contract_r)
    result_r = backend_r.resolve_approval(ap_r)
    assert result_r["choice"] == "deny", "REVOKED 决议不得被 grant 升级"
    assert result_r.get("consumed") is not True
    assert len(_onces_for(server, run_id_r)) == 0, "REVOKED 升级路径零 once"
    backend_r.close()


# --------------------------------------------------------------- P4-2: 重投 exactly-once
def test_61_reviewer_approval_replay_exactly_once(server):
    """P4-locked（blocker 二）：相同 (run, tool, capability, 完整原始 args) 重投
    复用原 approval_id——PENDING 复用、APPROVED 未 forward 交唯一 resolve 路径、
    resolve 后重投 Hermes POST 数不增加；传输层字段（timestamp）差异不构成新操作；
    不同操作仍是新 approval；并发相同操作只产生一个 approval_id 且零转发 POST。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p4_replay")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract))
    handle = backend.submit(contract.to_backend_projection())
    record = backend._runs[handle.run_id]
    frame = {"event": "approval.request", "tool": "terminal",
             "command": "echo replay", "preview": "echo replay", "timestamp": 1.0}
    a1, r1 = backend._handle_approval_request(handle.run_id, record, dict(frame))
    assert a1 and r1 is None
    # PENDING 重投：复用原 approval_id；零新 16D request、零转发 POST
    assert backend._handle_approval_request(
        handle.run_id, record, dict(frame)) == (a1, None)
    assert backend._handle_approval_request(
        handle.run_id, record, {**frame, "timestamp": 999.0}) == (a1, None), \
        "传输层字段（timestamp）不参与操作身份"
    assert len(_requested_events(broker)) == 1
    assert server.approval_requests == [], "PENDING 重投零转发"
    assert len(backend._approval_ops) == 1
    # APPROVED 但尚未 forward：重投仍交唯一 resolve 路径（不旁路 _approval_forwarded）
    assert broker.resolve(a1, ApprovalDecisionKind.APPROVE_ONCE).ok
    assert backend._handle_approval_request(
        handle.run_id, record, dict(frame)) == (a1, None)
    assert server.approval_requests == []
    # 唯一 resolve 路径 → 恰好一个 once
    result = backend.resolve_approval(a1)
    assert result["choice"] == "once" and result["resolved"] == 1
    assert server.approval_requests == [(handle.run_id, {"choice": "once"})]
    # resolve 后重投：Hermes POST 数不增加
    assert backend._handle_approval_request(
        handle.run_id, record, dict(frame)) == (a1, None)
    assert len(server.approval_requests) == 1, "resolve 后重投零新增 POST"
    # 不同完整原始 args = 不同操作身份 → 新 approval
    a2, r2 = backend._handle_approval_request(
        handle.run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo other", "preview": "echo other"})
    assert a2 is not None and a2 != a1 and r2 is None
    assert len(backend._approval_ops) == 2
    backend.close()

    # 并发相同操作：in-flight 单飞只产生一个 approval_id，全部零转发 POST
    broker_c = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract_c = _make_contract(contract_id="wc_16c_p4_replay_conc")
    backend_c = _make_backend(server, broker=broker_c, contract=contract_c,
                              approval_gates=_make_gates(broker_c, contract_c))
    handle_c = backend_c.submit(contract_c.to_backend_projection())
    record_c = backend_c._runs[handle_c.run_id]
    frame_c = {"event": "approval.request", "tool": "terminal",
               "command": "echo concurrent", "preview": "echo concurrent"}
    outcomes: List[Tuple[Optional[str], Optional[str]]] = []
    barrier = threading.Barrier(4)
    olock = threading.Lock()

    def worker() -> None:
        barrier.wait(timeout=10)
        r = backend_c._handle_approval_request(handle_c.run_id, record_c,
                                               dict(frame_c))
        with olock:
            outcomes.append(r)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=15)
    assert len(outcomes) == 4
    ids = {a for a, _r in outcomes}
    assert len(ids) == 1 and all(r is None for _a, r in outcomes), \
        f"并发相同操作只产生一个 approval_id: {outcomes}"
    assert len(_requested_events(broker_c)) == 1, "并发重投零新 16D request"
    assert _denies_for(server, handle_c.run_id) == [] \
        and _onces_for(server, handle_c.run_id) == [], "并发重投零转发 POST"
    backend_c.close()


# --------------------------------------------------------------- P4-3: 容量保留幂等重投
def test_62_reviewer_idempotent_replay_survives_capacity(server):
    """P4-locked（blocker 三）：approval 账本容量满时——已存在的完全相同操作重投
    复用原 approval_id（零新账本、零新 broker request、零 deny POST）；只有新的
    不同操作才 approval_ledger_full + deny；并发相同操作在 cap=1 下也只产生一个
    approval_id、零容量 deny。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p4_cap_replay")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract),
                            max_tracked_approvals=1)
    handle = backend.submit(contract.to_backend_projection())
    record = backend._runs[handle.run_id]
    frame_a = {"event": "approval.request", "tool": "terminal",
               "command": "echo cap-a", "preview": "echo cap-a"}
    a, r = backend._handle_approval_request(handle.run_id, record, dict(frame_a))
    assert a and r is None
    # 新的不同操作：容量满 → approval_ledger_full + deny
    assert backend._handle_approval_request(
        handle.run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo cap-b", "preview": "echo cap-b"}) == \
        (None, "approval_ledger_full")
    assert len(_denies_for(server, handle.run_id)) == 1
    # 完全相同操作重投：容量满仍复用原 approval_id——不增加账本、不新建 broker
    # request、不向 Hermes 发 deny
    n_requested = len(_requested_events(broker))
    assert backend._handle_approval_request(
        handle.run_id, record, dict(frame_a)) == (a, None)
    assert len(_requested_events(broker)) == n_requested, "重投零新 broker request"
    assert len(_denies_for(server, handle.run_id)) == 1, "重投零新 deny POST"
    assert len(backend._approval_ops) == 1, "重投不增加账本"
    backend.close()

    # 并发相同操作（cap=1、账本为空起跑）：单飞后仍然只有一个 approval_id、
    # 零 approval_ledger_full、零 deny POST
    broker_c = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract_c = _make_contract(contract_id="wc_16c_p4_cap_conc")
    backend_c = _make_backend(server, broker=broker_c, contract=contract_c,
                              approval_gates=_make_gates(broker_c, contract_c),
                              max_tracked_approvals=1)
    handle_c = backend_c.submit(contract_c.to_backend_projection())
    record_c = backend_c._runs[handle_c.run_id]
    frame_c = {"event": "approval.request", "tool": "terminal",
               "command": "echo cap-conc", "preview": "echo cap-conc"}
    outcomes: List[Tuple[Optional[str], Optional[str]]] = []
    barrier = threading.Barrier(3)
    olock = threading.Lock()

    def worker() -> None:
        barrier.wait(timeout=10)
        r = backend_c._handle_approval_request(handle_c.run_id, record_c,
                                               dict(frame_c))
        with olock:
            outcomes.append(r)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(3)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=15)
    assert len(outcomes) == 3
    ids = {a_ for a_, _r in outcomes}
    assert len(ids) == 1 and None not in ids, \
        f"cap=1 并发相同操作也只产生一个 approval_id: {outcomes}"
    assert all(r_ is None for _a, r_ in outcomes), \
        f"幂等重投不产生容量拒绝: {outcomes}"
    assert len(_requested_events(broker_c)) == 1
    assert _denies_for(server, handle_c.run_id) == []
    assert len(backend_c._approval_ops) == 1
    backend_c.close()


# --------------------------------------------------------------- P4-4: 操作身份深度冻结
def test_63_reviewer_operation_snapshot_deeply_isolated(server):
    """P4-locked（blocker 四）：帧进入审批域即严格递归 defensive copy——事件 payload
    修改不污染账本身份；permission_decider 修改收到的嵌套参数不污染账本；resolve/
    permit 始终使用帧时刻冻结的原始操作；替换后的操作是新 approval 不借用许可；
    非 JSON 值 fail-closed；_ApprovalOpRecord 无重复 __slots__ 声明。"""
    import inspect

    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p4_freeze")
    seen: List[Dict[str, Any]] = []

    def decider(tool, capability, raw_args, contract_id, run_id):
        seen.append(json.loads(json.dumps(raw_args)))   # 捕获收到的独立副本快照
        raw_args.setdefault("opts", {}).setdefault("paths", []).append("/pm-mutated")
        raw_args["injected"] = "pm-side-effect"
        return PermissionDecision(True, "pm_allow", Permission.L2_HIGH_RISK)

    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract),
                            permission_decider=decider)
    handle = backend.submit(contract.to_backend_projection())
    run_id = handle.run_id
    frame = {"event": "approval.request", "tool": "terminal",
             "command": "echo freeze", "preview": "echo freeze",
             "opts": {"paths": ["/a", "/b"], "env": {"k": "v"}}}
    server.set_status_sequence(run_id, [("waiting_for_approval", {})])
    server.sse[run_id] = [("frame", frame), ("close",)]
    box: Dict[str, Any] = {}

    def consume() -> None:
        for be in backend.events(handle):
            if be.event_type == "approval.request":
                box["event"] = be

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    assert _wait_until(lambda: "event" in box)
    be = box["event"]
    approval_id = be.payload["approval_id"]
    op = backend._approval_ops[approval_id]
    # (1) 审批事件返回后修改 payload 内嵌 dict/list，账本身份不变（零共享嵌套引用）
    be.payload["opts"]["paths"].append("/evil")
    be.payload["opts"]["env"]["k"] = "evil"
    be.payload["injected"] = "payload-side-effect"
    assert op.op_args["opts"]["paths"] == ["/a", "/b"]
    assert op.op_args["opts"]["env"] == {"k": "v"}
    assert "injected" not in op.op_args
    # (2) permission_decider 修改收到的嵌套参数，账本身份不变（decider 持独立副本）
    assert seen, "decider 已被调用"
    assert seen[0]["opts"]["paths"] == ["/a", "/b"], \
        "decider 收到的必须是帧时刻冻结值的独立副本"
    assert op.op_args["opts"]["paths"] == ["/a", "/b"]
    assert "injected" not in op.op_args
    # (3) 原操作批准后只能消费原操作：resolve/Gate/permit 始终使用帧时刻冻结的
    #     原始操作（resolve 边界 decider 收到的仍是原始 args）
    assert broker.resolve(approval_id, ApprovalDecisionKind.APPROVE_ONCE).ok
    result = backend.resolve_approval(approval_id)
    assert result["choice"] == "once" and result["consumed"] is True
    assert seen[-1]["command"] == "echo freeze"
    assert seen[-1]["opts"]["paths"] == ["/a", "/b"]
    assert op.op_args["opts"]["paths"] == ["/a", "/b"]
    assert op.op_args["command"] == "echo freeze"
    # (4) 替换后的操作不能借用许可：篡改 args = 新操作身份 → 新 approval（PENDING），
    #     绝不借用已消费 approval 的 permit
    tampered = dict(frame)
    tampered["command"] = "echo EVIL"
    tampered["opts"] = {"paths": ["/evil"]}
    a2, r2 = backend._handle_approval_request(run_id, backend._runs[run_id],
                                              tampered)
    assert a2 is not None and a2 != approval_id and r2 is None, \
        "替换后的操作 ≠ 原操作身份（不得借用许可）"
    assert broker.state_of(a2) is ApprovalState.PENDING, \
        "替换后的操作必须走自己的审批，不得复用原许可"
    assert broker.is_consumed(approval_id)
    # (5) 非 JSON 值 fail-closed（零 16D 请求、零 once）
    n_requested = len(_requested_events(broker))
    n_onces = len(_onces_for(server, run_id))
    assert backend._handle_approval_request(
        run_id, backend._runs[run_id],
        {"event": "approval.request", "tool": "terminal",
         "command": object()}) == (None, "approval_args_not_canonical")
    assert backend._handle_approval_request(
        run_id, backend._runs[run_id],
        {"event": "approval.request", "tool": "terminal",
         "command": "echo nan", "n": float("nan")}) == \
        (None, "approval_args_not_canonical")
    assert backend._handle_approval_request(
        run_id, backend._runs[run_id],
        {"event": "approval.request", "tool": "terminal",
         "command": "echo set", "s": {1, 2}}) == \
        (None, "approval_args_not_canonical")
    assert len(_requested_events(broker)) == n_requested, "非 JSON 帧 零 16D 请求"
    assert len(_onces_for(server, run_id)) == n_onces, "非 JSON 帧 零 once（不新增转发）"
    # (6) _ApprovalOpRecord 恰好一个 __slots__ 声明（无重复声明）
    cls_src = inspect.getsource(hermes_module._ApprovalOpRecord)
    assert cls_src.count("__slots__") == 1, "_ApprovalOpRecord 不得重复声明 __slots__"
    t.join(timeout=10)
    backend.close()


# --------------------------------------------------------------- P4-5: Gate 绑定证明
def test_64_reviewer_gate_broker_binding_enforced(server):
    """P4-locked（blocker 五）：来自另一 ApprovalBroker 的 Gate——其 PENDING
    approval_id 在 adapter 构造期注入的 broker 上不可查询（公开 API state_of）→
    fail-closed deny、不进 adapter 账本、零 once；其 grant 不被 adapter broker
    承认（公开 API is_grant_active）→ 同样 fail-closed deny、零 once；对照组证明
    本 broker 的合法 grant 路径照常放行（绑定证明不误伤合法路径）。
    （外部 Gate 绑定的契约需 workspace 根供 grant 使用——与 test_43 同构，
    白盒 _RunRecord 驱动；run 经 server.register_run 注册使转发可观察。）"""
    ws = WorkspaceScope(read_roots=("C:/ws/p4",), write_roots=("C:/ws/p4",))
    contract = _make_contract(contract_id="wc_16c_p4_binding", workspace_scope=ws)
    broker_main = _make_evidence_broker()
    broker_foreign = _make_evidence_broker()
    foreign_gate = _make_gate(broker_foreign, contract)
    backend = _make_backend(server, broker=broker_main, contract=contract,
                            approval_gates={contract.contract_id: foreign_gate})
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    server.register_run(run_id)
    record = _RunRecord(contract.contract_id, contract.content_hash,
                        tuple(contract.allowed_capabilities), contract=contract)
    # (a) PENDING 路径：外部 Gate 的 approval_id 在本 broker 不可查询 → deny
    approval_id, r = backend._handle_approval_request(
        run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo foreign", "preview": "echo foreign"})
    assert approval_id is None and         r == "approval_gate_broker_binding",         f"外部 Gate 的 approval 必须被绑定证明拦截: {(approval_id, r)}"
    assert not _requested_events(broker_main),         "外部 Gate 的 approval 不进 adapter broker"
    assert backend._approval_ops == {}, "不进入 adapter approval 账本"
    denies = _denies_for(server, run_id)
    assert denies and all(b.get("choice") == "deny" for b in denies)
    assert _onces_for(server, run_id) == [], "外部 Gate 零 once"
    assert _requested_events(broker_foreign),         "前置：外部 Gate 确实曾在自己的 broker 建立审批（被绑定证明拦截）"
    # (b) grant 路径：外部 broker 的 grant 不被 adapter broker 承认 → deny
    _create_session_grant(broker_foreign, contract)
    r2 = backend._handle_approval_request(
        run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo fgrant", "preview": "echo fgrant"})
    assert r2 == (None, "approval_gate_broker_binding_grant"),         f"外部 broker 的 grant 必须被绑定证明拦截: {r2}"
    assert _onces_for(server, run_id) == []
    # (c) 对照组：本 broker 的合法 grant + 绑定本 broker 的 Gate → grant-covered
    #     once 照常放行（绑定证明只拦截"Gate/broker 来自外部"的组合）
    main_gate = _make_gate(broker_main, contract)
    backend_main = _make_backend(server, broker=broker_main, contract=contract,
                                 approval_gates={contract.contract_id: main_gate})
    _create_session_grant(broker_main, contract)
    r3 = backend_main._handle_approval_request(
        run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo mgrant", "preview": "echo mgrant"})
    assert r3 == (None, "approval_covered_by_grant_once"),         f"本 broker 合法 grant 不得被绑定证明误伤: {r3}"
    assert len(_onces_for(server, run_id)) == 1
    backend.close()
    backend_main.close()


# --------------------------------------------------------------- P4-6: 词法与媒体类型收尾
def test_65_reviewer_tool_identity_exact_and_strict_charset(server):
    """P4-locked（blocker 六）：approval frame 的 tool 精确匹配——" terminal " 不得
    被 strip() 规范化成 "terminal"（自动 deny、零 16D 请求），精确 tool 主路径不受
    影响；content-type charset 参数真正 token 校验——重复 charset/空值/引号/空白/
    非法参数/与 UTF-8 解码矛盾的声明一律拒绝，正常 application/json 与
    application/json; charset=utf-8（任意大小写、可有可无空格）保持通过。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p4_exact_tool")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract))
    handle = backend.submit(contract.to_backend_projection())
    record = backend._runs[handle.run_id]
    # tool " terminal "：精确匹配失败 → approval_tool_unmapped（零规范化）
    r = backend._handle_approval_request(
        handle.run_id, record,
        {"event": "approval.request", "tool": " terminal ",
         "command": "echo pad", "preview": "echo pad"})
    assert r == (None, "approval_tool_unmapped"), \
        f"未规范化 tool 不得被 strip 成合法名字: {r}"
    assert not _requested_events(broker), "未规范化 tool 零 16D 请求"
    denies = _denies_for(server, handle.run_id)
    assert denies and all(b.get("choice") == "deny" for b in denies)
    assert _onces_for(server, handle.run_id) == []
    # 对照：精确 tool 主路径不受影响
    a, rr = backend._handle_approval_request(
        handle.run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo exact", "preview": "echo exact"})
    assert a and rr is None
    backend.close()

    # charset 严格校验（白盒直驱 _read_json_object）
    class _CtypeStub:
        def __init__(self, ctype: str) -> None:
            self.headers = {"content-type": ctype}

        def iter_bytes(self):
            yield b'{"ok": true}'

    for ctype in ("application/json",
                  "application/json;charset=utf-8",
                  "application/json; charset=utf-8",
                  "application/json; charset=UTF-8"):
        assert backend._read_json_object("t", _CtypeStub(ctype)) == {"ok": True}, \
            f"正常媒体类型必须保持通过: {ctype!r}"
    for ctype in ("application/json; charset=utf-8; charset=utf-8",  # 重复 charset
                  "application/json; charset=",                       # 空值
                  "application/json; charset='utf-8'",                # 引号（非 token）
                  "application/json; charset=ut f-8",                 # 空白（非 token）
                  "application/json; charset=utf-16",                 # 与严格 UTF-8 矛盾
                  "application/json; boundary=x; charset=utf-8",      # 非法参数
                  "application/json; charset=utf-8; x=y"):            # 非法参数
        with pytest.raises(HermesProtocolError, match="charset"):
            backend._read_json_object("t", _CtypeStub(ctype))
    backend.close()


# =================================================================================
# ================================ Reviewer Patch 5 专项 ============================
# =================================================================================

#: uuid4 桩的固定 hex（主/外部 broker 各自取 [:12] 生成**相同** approval_id/grant_id）。
_FIXED_UUID_HEX = "5c011d5ea12b5c011d5ea12b5c011d5e"


class _FixedUuid4:
    """uuid4 桩：``hex`` 固定——使两个 broker 在 UUID 碰撞前提下生成同名 ID
    （Reviewer Patch 5 blocker 一：同名 ID 但身份不同必须被绑定证明拒绝）。"""

    def __init__(self, hex_value: str = _FIXED_UUID_HEX) -> None:
        self.hex = hex_value


def _patch_uuid4(monkeypatch: pytest.MonkeyPatch,
                 hex_value: str = _FIXED_UUID_HEX) -> None:
    """全局替换 uuid.uuid4（broker/grant/nonce 生成全部同名化；测试结束自动还原）。"""
    monkeypatch.setattr(uuid, "uuid4", lambda: _FixedUuid4(hex_value))


def _p5_run_record(contract: WorkContract) -> _RunRecord:
    return _RunRecord(contract.contract_id, contract.content_hash,
                      tuple(contract.allowed_capabilities), contract=contract)


# ------------------------------------------------- P5-A: approval 同名 ID 碰撞拒绝
def test_66_reviewer_approval_binding_full_identity_uuid_collision(server, monkeypatch):
    """P5-locked（blocker 一/A）：monkeypatch UUID 使主 broker 与 foreign broker
    生成**相同** approval_id，但操作身份不同——foreign Gate 必须被完整身份绑定
    证明拒绝：不进 adapter 账本、不消费 permit、零 once、主 broker 原记录不覆盖
    不串用；对照组证明主 broker 自己的 Gate 对同一完整身份正例照常通过（同名 ID
    存在性从来不是证明依据，完整身份一致才是）。"""
    contract = _make_contract(contract_id="wc_16c_p5_apv_collision")
    broker_main = _make_evidence_broker()
    broker_foreign = _make_evidence_broker()
    backend = _make_backend(
        server, broker=broker_main, contract=contract,
        approval_gates={contract.contract_id: _make_gate(broker_foreign, contract)})
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    server.register_run(run_id)
    record = _p5_run_record(contract)
    _patch_uuid4(monkeypatch)
    # 主 broker 预置**同名 approval_id** 的不同操作记录（UUID 碰撞前提）；
    # args 与对照组帧的 canonical 操作参数完全一致（对照可复用同一条记录）。
    main_op_args = {"tool": "terminal", "command": "echo MAIN-SIDE-OP",
                    "preview": "echo MAIN-SIDE-OP"}
    planted = broker_main.create_request(
        contract_id=contract.contract_id, run_id=run_id, tool="terminal",
        capability="cap.filesystem", args=dict(main_op_args),
        reason="p5-collision-planted", risk_level=Permission.L2_HIGH_RISK,
        requested_scope=(), policy_kind="approval_required_each_step",
        contract_hash=contract.content_hash)
    assert planted.approval_id == f"apv_{_FIXED_UUID_HEX[:12]}", \
        "前置：UUID 桩必须使主 broker 生成固定同名 approval_id"
    n_main_requested = len(_requested_events(broker_main))
    # foreign Gate 处理**不同**操作 → foreign broker 生成同名 approval_id
    approval_id, r = backend._handle_approval_request(
        run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo FOREIGN-OP", "preview": "echo FOREIGN-OP"})
    assert approval_id is None and r == "approval_gate_broker_binding", \
        f"同名 ID 但身份不同的 foreign Gate 必须被拒绝: {(approval_id, r)}"
    assert len(_requested_events(broker_main)) == n_main_requested, \
        "碰撞操作零新主 broker request（原记录不被覆盖/串用）"
    assert backend._approval_ops == {} and backend._approval_op_index == {}, \
        "不进入 adapter approval 账本"
    assert _requested_events(broker_foreign), \
        "前置：foreign Gate 确实曾在自己的 broker 建立同名审批（被完整身份证明拦截）"
    denies = _denies_for(server, run_id)
    assert denies and all(b.get("choice") == "deny" for b in denies)
    assert _onces_for(server, run_id) == [], "碰撞拒绝零 once"
    assert broker_main.state_of(planted.approval_id) is ApprovalState.PENDING, \
        "主 broker 原记录状态不受碰撞影响"
    assert not broker_main.is_consumed(planted.approval_id), "原记录零消费"
    backend.close()
    # 对照组：主 broker 自己的 Gate 对**完整身份一致**的操作 → 正常建立（复用原
    # 记录、零新 broker request）——绑定证明只拒绝身份不一致的冒名，不误伤正例。
    backend_main = _make_backend(
        server, broker=broker_main, contract=contract,
        approval_gates={contract.contract_id: _make_gate(broker_main, contract)})
    a_ok, r_ok = backend_main._handle_approval_request(
        run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo MAIN-SIDE-OP", "preview": "echo MAIN-SIDE-OP"})
    assert a_ok == planted.approval_id and r_ok is None, \
        f"完整身份一致的正例必须通过绑定证明: {(a_ok, r_ok)}"
    assert len(_requested_events(broker_main)) == n_main_requested, \
        "正例复用既有记录（零新 broker request）"
    assert list(backend_main._approval_ops) == [planted.approval_id]
    backend_main.close()


# ------------------------------------------------- P5-B: 同名 ID 身份逐维否证
def test_67_reviewer_approval_binding_identity_dimension_negations(server, monkeypatch):
    """P5-locked（blocker 一/B）：相同 approval_id、相同 tool，但 args / run_id /
    contract hash 任一不同的同名主 broker 记录，均不得通过绑定证明（逐维否证，
    零账本零 once）；完整身份一致的正例保持通过。"""
    contract = _make_contract(contract_id="wc_16c_p5_dims")
    frame = {"event": "approval.request", "tool": "terminal",
             "command": "echo B-FRAME", "preview": "echo B-FRAME"}
    frame_args = {"tool": "terminal", "command": "echo B-FRAME",
                  "preview": "echo B-FRAME"}
    # run_id 在 UUID 桩生效**前**生成（保持互相独立，避免桩固定 run_id 混淆维度）
    run_a = f"run_{uuid.uuid4().hex[:12]}"
    run_b = f"run_{uuid.uuid4().hex[:12]}"
    run_c = f"run_{uuid.uuid4().hex[:12]}"
    for rid in (run_a, run_b, run_c, "run_p5_positive"):
        server.register_run(rid)

    def planted_request(broker: ApprovalBroker, **overrides: Any) -> Any:
        params: Dict[str, Any] = dict(
            contract_id=contract.contract_id, tool="terminal",
            capability="cap.filesystem", args=dict(frame_args),
            reason="p5-dim-negation", risk_level=Permission.L2_HIGH_RISK,
            requested_scope=(), policy_kind="approval_required_each_step",
            contract_hash=contract.content_hash)
        params.update(overrides)
        return broker.create_request(**params)

    def foreign_backend(broker_main: ApprovalBroker) -> HermesExecutionBackend:
        return _make_backend(
            server, broker=broker_main, contract=contract,
            approval_gates={contract.contract_id:
                            _make_gate(_make_evidence_broker(), contract)})

    # (1) 同名 ID + 同 tool/run/契约但**不同 args**（operation digest 必不同）
    _patch_uuid4(monkeypatch)
    broker_a = _make_evidence_broker()
    backend_a = foreign_backend(broker_a)
    planted_request(broker_a, run_id=run_a,
                    args={"tool": "terminal", "command": "echo B-OTHER-ARGS",
                          "preview": "echo B-OTHER-ARGS"})
    assert backend_a._handle_approval_request(
        run_a, _p5_run_record(contract), dict(frame)) == \
        (None, "approval_gate_broker_binding"), "不同 args 的同名记录不得通过"
    assert backend_a._approval_ops == {} and _onces_for(server, run_a) == []
    backend_a.close()

    # (2) 同名 ID + 同 tool/args/契约但**不同 run_id**
    broker_b = _make_evidence_broker()
    backend_b = foreign_backend(broker_b)
    planted_request(broker_b, run_id="run_p5_other_run")
    assert backend_b._handle_approval_request(
        run_b, _p5_run_record(contract), dict(frame)) == \
        (None, "approval_gate_broker_binding"), "不同 run_id 的同名记录不得通过"
    assert backend_b._approval_ops == {} and _onces_for(server, run_b) == []
    backend_b.close()

    # (3) 同名 ID + 同 tool/args/run_id 但**不同 contract hash**
    broker_c = _make_evidence_broker()
    backend_c = foreign_backend(broker_c)
    planted_request(broker_c, run_id=run_c, contract_hash="0" * 64)
    assert backend_c._handle_approval_request(
        run_c, _p5_run_record(contract), dict(frame)) == \
        (None, "approval_gate_broker_binding"), "不同契约 hash 的同名记录不得通过"
    assert backend_c._approval_ops == {} and _onces_for(server, run_c) == []
    backend_c.close()

    # (4) 正例：完整身份逐维一致（主 broker Gate）→ 通过
    broker_d = _make_evidence_broker()
    planted = planted_request(broker_d, run_id="run_p5_positive")
    backend_d = _make_backend(
        server, broker=broker_d, contract=contract,
        approval_gates={contract.contract_id: _make_gate(broker_d, contract)})
    a_ok, r_ok = backend_d._handle_approval_request(
        "run_p5_positive", _p5_run_record(contract), dict(frame))
    assert a_ok == planted.approval_id and r_ok is None, \
        f"完整身份一致的正例必须通过: {(a_ok, r_ok)}"
    assert list(backend_d._approval_ops) == [planted.approval_id]
    backend_d.close()


# ------------------------------------------------- P5-C: grant 同名 ID 碰撞拒绝
def test_68_reviewer_grant_binding_full_identity_collision(server, monkeypatch):
    """P5-locked（blocker 一/C）：monkeypatch UUID 使主 broker 与 foreign broker
    生成**相同** grant_id——主 broker 中是有效但不同 tool / 不同 contract 的
    grant，foreign Gate 返回同名覆盖 grant → 必须拒绝：零 permit 消费、零 once；
    主 broker 合法覆盖 grant 正例保持通过（D）。"""
    ws = WorkspaceScope(read_roots=("C:/ws/p5",), write_roots=("C:/ws/p5",))
    contract = _make_contract(contract_id="wc_16c_p5_grant_collision", workspace_scope=ws)
    other_contract = _make_contract(contract_id="wc_16c_p5_grant_other", workspace_scope=ws)
    frame = {"event": "approval.request", "tool": "terminal",
             "command": "echo g", "preview": "echo g"}
    # run_id 在 UUID 桩生效**前**生成（互相独立；桩后 uuid4 恒返回固定 hex）
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    run_id_b = f"run_{uuid.uuid4().hex[:12]}"
    run_id_c = f"run_{uuid.uuid4().hex[:12]}"
    for rid in (run_id, run_id_b, run_id_c):
        server.register_run(rid)
    _patch_uuid4(monkeypatch)

    # (a) 主 broker：同契约但 tool_pattern 不覆盖 terminal 的**有效** grant（同名 id）
    broker_main = _make_evidence_broker()
    main_grant_a = _create_session_grant(broker_main, contract, tool_pattern="read_file")
    assert main_grant_a.grant_id == f"gr_{_FIXED_UUID_HEX[:12]}", \
        "前置：UUID 桩必须使主 broker 生成固定同名 grant_id"
    assert broker_main.is_grant_active(main_grant_a.grant_id), "前置：同名 grant 有效"
    broker_foreign = _make_evidence_broker()
    _create_session_grant(broker_foreign, contract)   # foreign broker 的覆盖 grant（同名 id）
    foreign_gate = _make_gate(broker_foreign, contract)
    consume_seen: List[Any] = []
    original_consume = foreign_gate.consume_permit

    def _recording_consume(permit: Any, *, tool: str, capability: str,
                           args: Mapping[str, Any]) -> Any:
        consume_seen.append(permit)
        return original_consume(permit, tool=tool, capability=capability, args=args)

    foreign_gate.consume_permit = _recording_consume   # type: ignore[method-assign]
    backend = _make_backend(server, broker=broker_main, contract=contract,
                            approval_gates={contract.contract_id: foreign_gate})
    record = _p5_run_record(contract)
    r = backend._handle_approval_request(run_id, record, dict(frame))
    assert r == (None, "approval_gate_broker_binding_grant"), \
        f"同名但不同 tool 的 grant 必须被完整身份证明拒绝: {r}"
    assert consume_seen == [], "证明失败绝不消费 permit（含外部 broker 的 permit）"
    assert _onces_for(server, run_id) == [], "碰撞拒绝零 once"
    denies = _denies_for(server, run_id)
    assert denies and all(b.get("choice") == "deny" for b in denies)
    backend.close()

    # (b) 主 broker：tool 覆盖但绑定**另一契约**的有效 grant（同名 id）
    broker_main_b = _make_evidence_broker()
    main_grant_b = _create_session_grant(broker_main_b, other_contract)
    assert main_grant_b.grant_id == f"gr_{_FIXED_UUID_HEX[:12]}"
    assert broker_main_b.is_grant_active(main_grant_b.grant_id)
    broker_foreign_b = _make_evidence_broker()
    _create_session_grant(broker_foreign_b, contract)
    backend_b = _make_backend(
        server, broker=broker_main_b, contract=contract,
        approval_gates={contract.contract_id: _make_gate(broker_foreign_b, contract)})
    r_b = backend_b._handle_approval_request(run_id_b, _p5_run_record(contract),
                                             dict(frame))
    assert r_b == (None, "approval_gate_broker_binding_grant"), \
        f"同名但绑定另一契约的 grant 必须被拒绝: {r_b}"
    assert _onces_for(server, run_id_b) == []
    backend_b.close()

    # (c) 对照组（D 正例）：全新主 broker + 合法**覆盖** grant + 主 broker Gate →
    #     立即边界消费 → once（完整身份证明不误伤合法 grant 路径；独立 broker
    #     避免同名 canonical USER event 在同一 broker 内被一次性绑定语义锁定）
    broker_main_c = _make_evidence_broker()
    main_cover = _create_session_grant(broker_main_c, contract)   # 覆盖 terminal
    assert main_cover.grant_id == f"gr_{_FIXED_UUID_HEX[:12]}"
    backend_main = _make_backend(
        server, broker=broker_main_c, contract=contract,
        approval_gates={contract.contract_id: _make_gate(broker_main_c, contract)})
    r3 = backend_main._handle_approval_request(run_id_c, _p5_run_record(contract),
                                               dict(frame))
    assert r3 == (None, "approval_covered_by_grant_once"), \
        f"主 broker 合法覆盖 grant 不得被绑定证明误伤: {r3}"
    assert len(_onces_for(server, run_id_c)) == 1
    backend_main.close()


# ------------------------------------------------- P5-D: 合法正例保持通过
def test_69_reviewer_binding_positive_paths_preserved(server):
    """P5-locked（blocker 一/D）：主 broker 合法 approval 与合法 grant 正例在完整
    身份绑定证明下保持通过——PENDING 建立账本、APPROVE_ONCE 后 resolve 经
    resolve 边界二次 Gate + 绑定证明 + 原子消费 → 恰好一个 once；grant 覆盖
    操作 → 立即边界消费 → once。"""
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p5_positive")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract))
    handle = backend.submit(contract.to_backend_projection())
    record = backend._runs[handle.run_id]
    frame = {"event": "approval.request", "tool": "terminal",
             "command": "echo p5-ok", "preview": "echo p5-ok"}
    a1, r1 = backend._handle_approval_request(handle.run_id, record, dict(frame))
    assert a1 and r1 is None, f"合法 approval 正例必须建立待审批记录: {(a1, r1)}"
    assert list(backend._approval_ops) == [a1]
    assert broker.state_of(a1) is ApprovalState.PENDING
    assert broker.resolve(a1, ApprovalDecisionKind.APPROVE_ONCE).ok
    result = backend.resolve_approval(a1)
    assert result["choice"] == "once" and result["resolved"] == 1, \
        f"APPROVE_ONCE 正例必须恰好转发一次 once: {result}"
    assert result["consumed"] is True
    assert broker.is_consumed(a1)
    assert server.approval_requests == [(handle.run_id, {"choice": "once"})]
    backend.close()

    # grant 正例：主 broker 合法覆盖 grant → 立即边界消费 → once
    ws = WorkspaceScope(read_roots=("C:/ws/p5",), write_roots=("C:/ws/p5",))
    contract_g = _make_contract(contract_id="wc_16c_p5_positive_grant", workspace_scope=ws)
    broker_g = _make_evidence_broker()
    backend_g = _make_backend(
        server, broker=broker_g, contract=contract_g,
        approval_gates={contract_g.contract_id: _make_gate(broker_g, contract_g)})
    run_id_g = f"run_{uuid.uuid4().hex[:12]}"
    server.register_run(run_id_g)
    _create_session_grant(broker_g, contract_g)
    r2 = backend_g._handle_approval_request(
        run_id_g, _p5_run_record(contract_g),
        {"event": "approval.request", "tool": "terminal",
         "command": "echo p5-grant-ok", "preview": "echo p5-grant-ok"})
    assert r2 == (None, "approval_covered_by_grant_once"), \
        f"合法 grant 正例不得被绑定证明误伤: {r2}"
    assert len(_onces_for(server, run_id_g)) == 1
    backend_g.close()


# ------------------------------------------------- P5-E: strict JSON 值域收尾
def test_70_reviewer_deep_freeze_strict_json_domain(server):
    """P5-locked（strict JSON 收尾）：``_deep_freeze_json`` 只接受真正 JSON 值域
    ——tuple（顶层/嵌套）一律 fail-closed，不得静默转换为 list；帧路径折为
    ``approval_args_not_canonical``（零 16D 请求、仅 deny 转发）；既有 JSON 正例
    （dict/list/str/int/float/bool/None 任意嵌套）保持通过且零共享嵌套引用。"""
    # (1) 既有 JSON 正例保持通过 + 零共享嵌套引用（dict/list 全部重建）
    src = {"a": [1, 2.5, True, None, "x", {"b": ["y", ["z"]]}], "c": {}, "d": []}
    out = hermes_module._deep_freeze_json(src)
    assert out == src
    assert out is not src and out["a"] is not src["a"] \
        and out["a"][5] is not src["a"][5] and out["a"][5]["b"] is not src["a"][5]["b"]
    out["a"].append("mutated")
    out["a"][5]["b"].append("mutated")
    assert src["a"] == [1, 2.5, True, None, "x", {"b": ["y", ["z"]]}], \
        "输出树修改不得污染输入树（零共享嵌套引用）"
    # (2) tuple 否证：顶层 / 嵌套 / dict 键值内一律拒绝（不得静默转 list）
    with pytest.raises(HermesProtocolError, match="tuple"):
        hermes_module._deep_freeze_json((1, 2))
    with pytest.raises(HermesProtocolError, match="tuple"):
        hermes_module._deep_freeze_json({"argv": ("echo", "hi")})
    with pytest.raises(HermesProtocolError, match="tuple"):
        hermes_module._deep_freeze_json({"deep": {"argv": [{"x": (1,)}]}})
    # (3) 帧路径：tuple → approval_args_not_canonical（零 16D 请求、仅 deny 转发）
    broker = ApprovalBroker(owner_thread_id=threading.get_ident())
    contract = _make_contract(contract_id="wc_16c_p5_tuple")
    backend = _make_backend(server, broker=broker, contract=contract,
                            approval_gates=_make_gates(broker, contract))
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    server.register_run(run_id)
    record = _p5_run_record(contract)
    n_requested = len(_requested_events(broker))
    assert backend._handle_approval_request(
        run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo tup", "argv": ("echo", "hi")}) == \
        (None, "approval_args_not_canonical"), "tuple 顶层出现必须 fail-closed"
    assert backend._handle_approval_request(
        run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo tup2", "opts": {"argv": ["ok", ("a", "b")]}}) == \
        (None, "approval_args_not_canonical"), "嵌套 tuple 必须 fail-closed"
    assert len(_requested_events(broker)) == n_requested, "tuple 帧零 16D 请求"
    assert _onces_for(server, run_id) == [], "tuple 帧零 once"
    assert len(_denies_for(server, run_id)) == 2, "tuple 帧仅自动 deny 转发"
    # 对照：等价 list 帧是合法 JSON 值域 → 正常建立审批（正例不回归）
    a, r = backend._handle_approval_request(
        run_id, record,
        {"event": "approval.request", "tool": "terminal",
         "command": "echo list-ok", "argv": ["echo", "hi"]})
    assert a and r is None, f"等价 list 帧必须正常建立审批: {(a, r)}"
    backend.close()
