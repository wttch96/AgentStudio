"""REST 与 SSE 接口。"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from pydantic import ValidationError

from app.domain.configuration import (
    AgentUpdate,
    BrainConfiguration,
    SchedulerConfiguration,
    SkillCreate,
    SkillUpdate,
    WorkspaceUpdate,
)
from app.domain.models import CreateRunRequest
from app.services.container import ServiceContainer
from app.storage.sqlite_store import TERMINAL_STATUSES


api = Blueprint("api", __name__)


def services() -> ServiceContainer:
    return current_app.extensions["services"]


@api.get("/status")
def status():
    settings = services().settings
    # 仅返回布尔值，绝不把环境中的密钥发送给浏览器。
    return jsonify(
        {
            "demo_mode": settings.demo_mode,
            "deepseek_configured": bool(settings.deepseek_api_key),
            "claude_configured": settings.claude_configured,
            "claude_route": settings.claude_route,
            "deepseek_model": settings.deepseek_model,
            "claude_model": settings.claude_model,
            "access": "local-only",
            "workspace_root": str(services().workspace.current()),
        }
    )


@api.get("/agents")
def agents():
    return jsonify({"items": services().registry.list_public()})


@api.get("/agents/<name>")
def get_agent(name: str):
    try:
        return jsonify(services().registry.get_public(name))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@api.put("/agents/<name>")
def update_agent(name: str):
    try:
        payload = AgentUpdate.model_validate(request.get_json(silent=True) or {})
        unknown_skills = set(payload.skills) - services().skills.names()
        if unknown_skills:
            return jsonify({"error": f"引用了未知 Skill: {sorted(unknown_skills)}"}), 400
        agent = services().registry.update(name, **payload.model_dump())
        return jsonify(agent)
    except ValidationError as error:
        return jsonify({"error": "Agent 配置无效", "details": error.errors()}), 400
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@api.get("/skills")
def skills():
    return jsonify({"items": services().skills.list_public()})


@api.get("/skills/<name>")
def get_skill(name: str):
    try:
        return jsonify(services().skills.get_public(name))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@api.post("/skills")
def create_skill():
    try:
        payload = SkillCreate.model_validate(request.get_json(silent=True) or {})
        skill = services().skills.create(**payload.model_dump())
        return jsonify(skill), 201
    except ValidationError as error:
        return jsonify({"error": "Skill 配置无效", "details": error.errors()}), 400
    except FileExistsError as error:
        return jsonify({"error": str(error)}), 409


@api.put("/skills/<name>")
def update_skill(name: str):
    try:
        payload = SkillUpdate.model_validate(request.get_json(silent=True) or {})
        skill = services().skills.update(name, **payload.model_dump())
        return jsonify(skill)
    except ValidationError as error:
        return jsonify({"error": "Skill 配置无效", "details": error.errors()}), 400
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@api.get("/workspace")
def get_workspace():
    return jsonify({"path": str(services().workspace.current())})


@api.put("/workspace")
def update_workspace():
    try:
        payload = WorkspaceUpdate.model_validate(request.get_json(silent=True) or {})
        root = services().workspace.update(payload.path)
        return jsonify({"path": str(root)})
    except ValidationError as error:
        return jsonify({"error": "工作目录配置无效", "details": error.errors()}), 400
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@api.get("/workspace/directories")
def browse_workspace():
    try:
        return jsonify(services().workspace.browse(request.args.get("path")))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@api.get("/scheduler")
def get_scheduler():
    return jsonify(services().scheduler.current().model_dump())


@api.put("/scheduler")
def update_scheduler():
    try:
        payload = SchedulerConfiguration.model_validate(request.get_json(silent=True) or {})
        return jsonify(services().scheduler.update(payload).model_dump())
    except ValidationError as error:
        return jsonify({"error": "调度配置无效", "details": error.errors()}), 400


@api.get("/brain")
def get_brain():
    return jsonify(services().brain.current().model_dump())


@api.get("/brain/default")
def get_default_brain():
    return jsonify(services().brain.default().model_dump())


@api.put("/brain")
def update_brain():
    try:
        payload = BrainConfiguration.model_validate(request.get_json(silent=True) or {})
        return jsonify(services().brain.update(payload).model_dump())
    except ValidationError as error:
        return jsonify({"error": "主脑配置无效", "details": error.errors()}), 400


@api.get("/deepseek/balance")
def deepseek_balance():
    refresh = request.args.get("refresh") == "1"
    return jsonify(services().deepseek_balance.current(refresh=refresh))


@api.get("/deepseek/usage")
def deepseek_usage():
    return jsonify(services().deepseek_usage.summary())


@api.post("/runs")
def create_run():
    try:
        payload = CreateRunRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as error:
        return jsonify({"error": "请求内容无效", "details": error.errors()}), 400
    try:
        return jsonify(
            services().runs.start(payload.objective, payload.parent_run_id)
        ), 202
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 409
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@api.get("/runs")
def list_runs():
    return jsonify({"items": services().store.list_runs()})


@api.get("/runs/<run_id>")
def get_run(run_id: str):
    run = services().store.get_run(run_id)
    if not run:
        return jsonify({"error": "运行不存在"}), 404
    run["events"] = services().store.list_events(run_id)
    return jsonify(run)


@api.delete("/runs/<run_id>")
def delete_run(run_id: str):
    # 数据库可能保留重启前的 running 状态；没有当前进程 worker 时可安全删除。
    result = services().store.delete_run(
        run_id,
        allow_orphaned_active=not services().runs.is_active(run_id),
    )
    if result == "not_found":
        return jsonify({"error": "运行不存在"}), 404
    if result == "active":
        return jsonify({"error": "运行仍在执行，请先停止并等待任务结束"}), 409
    return "", 204


@api.post("/runs/<run_id>/cancel")
def cancel_run(run_id: str):
    if not services().store.get_run(run_id):
        return jsonify({"error": "运行不存在"}), 404
    accepted = services().runs.cancel(run_id)
    return jsonify({"accepted": accepted}), 202 if accepted else 409


@api.get("/runs/<run_id>/events")
def list_events(run_id: str):
    after = max(0, request.args.get("after", default=0, type=int))
    return jsonify({"items": services().store.list_events(run_id, after)})


@api.get("/runs/<run_id>/stream")
def stream_events(run_id: str):
    if not services().store.get_run(run_id):
        return jsonify({"error": "运行不存在"}), 404

    after = max(0, request.args.get("after", default=0, type=int))

    @stream_with_context
    def generate() -> Iterator[str]:
        sequence = after
        idle_ticks = 0
        while True:
            events = services().store.list_events(run_id, sequence)
            for event in events:
                sequence = event["sequence"]
                yield f"id: {sequence}\nevent: run-event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            run = services().store.get_run(run_id)
            if run and run["status"] in TERMINAL_STATUSES and not events:
                break

            idle_ticks += 1
            if idle_ticks % 15 == 0:
                # SSE 注释心跳能防止代理或浏览器误判空闲连接断开。
                yield ": keep-alive\n\n"
            time.sleep(0.2)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
