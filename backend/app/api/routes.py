"""REST 与 SSE 接口。"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from pydantic import ValidationError

from app.domain.configuration import (
    MemoryConfiguration,
    AgentUpdate,
    BrainConfiguration,
    SchedulerConfiguration,
    SkillCreate,
    SkillUpdate,
    WorkspaceUpdate,
)
from app.domain.models import (
    CreateRunRequest,
    CreateProjectRequest,
    Project,
    ProjectAgent,
    AgentTemplate,
    KnowledgeEntry,
    KnowledgeRelation,
    KnowledgeFeedback,
    InterruptAction,
    InterruptCommand,
    InterruptTarget,
)
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
    project_id = request.args.get("project_id", "")
    return jsonify({"items": services().registry.list_public(project_id)})


@api.get("/agents/<name>")
def get_agent(name: str):
    project_id = request.args.get("project_id", "")
    if not project_id:
        return jsonify({"error": "需要指定 project_id"}), 400
    try:
        agent_profiles = services().registry.load_project_agents(project_id)
        profile = agent_profiles.get(name)
        if not profile:
            return jsonify({"error": f"Agent {name} 不存在"}), 404
        return jsonify({
            "id": getattr(profile, "id", ""),
            "name": profile.name,
            "display_name": profile.display_name,
            "description": profile.description,
            "prompt": profile.prompt,
            "tools": list(profile.tools),
            "skills": list(profile.skills),
            "skill_count": len(profile.skills),
            "sub_dir": profile.sub_dir,
            "is_required": profile.is_required,
            "agent_type": profile.agent_type,
        })
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@api.put("/agents/<name>")
def update_agent(name: str):
    # Agent 配置现在通过 /api/projects/<id>/agents/<id> 管理
    return jsonify({"error": "请使用 /api/projects/<id>/agents/<id> 更新项目 Agent"}), 400
# old update_agent placeholder
def _old_update_agent(name: str):
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
    project_id = request.args.get("project_id", "")
    if project_id:
        return jsonify({"items": services().skills.list_project(project_id)})
    return jsonify({"items": services().skills.list_public()})


@api.get("/skills/<name>")
def get_skill(name: str):
    project_id = request.args.get("project_id", "")
    try:
        if project_id:
            return jsonify(services().skills.get_project(project_id, name))
        return jsonify(services().skills.get_public(name))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@api.post("/skills")
def create_skill():
    try:
        payload = SkillCreate.model_validate(request.get_json(silent=True) or {})
        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id", "")
        if project_id:
            skill = services().skills.create_project(project_id, **payload.model_dump())
        else:
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
        project_id = request.args.get("project_id", "")
        if project_id:
            skill = services().skills.update_project(project_id, name, **payload.model_dump())
        else:
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
            services().runs.start(payload.objective, payload.parent_run_id,
                                  project_id=payload.project_id)
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

@api.post("/runs/<run_id>/fork")
def fork_run(run_id: str):
    """从已完成的任务中分叉（fork），携带记忆上下文开启新对话分支。"""
    source = services().store.get_run(run_id)
    if not source:
        return jsonify({"error": "源任务不存在"}), 404
    if source.get("status") not in ("completed", "failed", "cancelled"):
        return jsonify({"error": "源任务尚未结束，请等待完成后再分叉"}), 409
    data = request.get_json(silent=True) or {}
    objective = (data.get("objective") or source.get("objective", "")).strip()
    if not objective:
        return jsonify({"error": "目标不能为空"}), 400
    try:
        run = services().runs.fork(run_id, objective_override=objective)
        preview = services().store.get_fork_preview(run_id)
        return jsonify({**run, "fork_preview": preview}), 202
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 409


@api.get("/runs/<run_id>/events")
def list_events(run_id: str):
    after = max(0, request.args.get("after", default=0, type=int))
    return jsonify({"items": services().store.list_events(run_id, after)})


# ==================== 记忆配置 ====================

@api.get("/memory")
def get_memory_config():
    return jsonify(services().memory_settings.current().model_dump())


@api.put("/memory")
def update_memory_config():
    try:
        payload = MemoryConfiguration.model_validate(request.get_json(silent=True) or {})
        return jsonify(services().memory_settings.update(payload).model_dump())
    except ValidationError as error:
        return jsonify({"error": "记忆配置无效", "details": error.errors()}), 400


@api.get("/memory/stats/<conversation_id>")
def get_memory_stats(conversation_id: str):
    """返回对话的记忆统计：各级别记忆条数、token 节省量等。"""
    return jsonify(services().memory_manager.get_stats(conversation_id))


# ==================== 中断指令 ====================

@api.post("/runs/<run_id>/interrupt")
def send_interrupt(run_id: str):
    """发送中断指令：暂停 agent、触发重规划或中止运行。"""
    if not services().store.get_run(run_id):
        return jsonify({"error": "运行不存在"}), 404
    try:
        data = request.get_json(silent=True) or {}
        command = InterruptCommand(
            run_id=run_id,
            target=InterruptTarget(data.get("target", "all")),
            action=InterruptAction(data.get("action", "pause")),
            target_agent=data.get("target_agent"),
            target_task=data.get("target_task"),
            instruction=data.get("instruction", ""),
        )
        command_id = services().interrupt_router.send(command)
        return jsonify({"id": command_id, "accepted": True}), 202
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@api.post("/runs/<run_id>/resume")
def resume_run(run_id: str):
    """恢复被中断的运行，可携带更新后的指令。"""
    if not services().store.get_run(run_id):
        return jsonify({"error": "运行不存在"}), 404
    payload = request.get_json(silent=True) or {}
    command_id = payload.get("command_id", "")
    decision = payload.get("decision", "apply")
    services().interrupt_router.resolve(run_id, command_id, decision)
    return jsonify({"accepted": True}), 202


# ==================== 知识库 API ====================

@api.get("/knowledge")
def search_knowledge():
    """搜索知识：?q=关键词&category=&top_k=10"""
    q = request.args.get("q", "")
    category = request.args.get("category")
    top_k = request.args.get("top_k", default=10, type=int)
    project_id = request.args.get("project_id", "")
    if not q:
        items = services().knowledge_store.list(category=category, project_id=project_id)
    else:
        items = services().knowledge_store.search(q, category=category, top_k=top_k, project_id=project_id)
    return jsonify({"items": items})


@api.get("/knowledge/<entry_id>")
def get_knowledge(entry_id: str):
    entry = services().knowledge_store.get(entry_id)
    if not entry:
        return jsonify({"error": "知识条目不存在"}), 404
    entry["relations"] = services().knowledge_store.get_relations(entry_id)
    return jsonify(entry)


@api.post("/knowledge")
def create_knowledge():
    try:
        payload = KnowledgeEntry.model_validate(request.get_json(silent=True) or {})
    except ValidationError as error:
        return jsonify({"error": "知识条目无效", "details": error.errors()}), 400
    data = request.get_json(silent=True) or {}
    entry_id = services().knowledge_store.add(
        title=payload.title, content=payload.content,
        category=payload.category, tags=payload.tags,
        source=payload.source, expires_at=payload.expires_at,
        project_id=data.get("project_id", ""),
    )
    return jsonify({"id": entry_id}), 201


@api.put("/knowledge/<entry_id>")
def update_knowledge(entry_id: str):
    payload = request.get_json(silent=True) or {}
    ok = services().knowledge_store.update(entry_id, **payload)
    if not ok:
        return jsonify({"error": "知识条目不存在或无可更新字段"}), 404
    return jsonify({"id": entry_id})


@api.delete("/knowledge/<entry_id>")
def delete_knowledge(entry_id: str):
    ok = services().knowledge_store.delete(entry_id)
    if not ok:
        return jsonify({"error": "知识条目不存在"}), 404
    return "", 204


@api.post("/knowledge/import")
def import_knowledge():
    """从工作区文件导入知识：读取 .md/.txt 文件，按标题拆分并批量创建条目。"""
    data = request.get_json(silent=True) or {}
    filepath = (data.get("filepath") or "").strip()
    category = (data.get("category") or "general").strip()
    project_id = (data.get("project_id") or "").strip()
    if not filepath:
        return jsonify({"error": "filepath 不能为空"}), 400
    try:
        result = services().knowledge_store.import_file(filepath, category, project_id=project_id)
        return jsonify(result), 201
    except FileNotFoundError:
        return jsonify({"error": f"文件不存在: {filepath}"}), 404
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

@api.get("/knowledge/<entry_id>/relations")
def get_knowledge_relations(entry_id: str):
    return jsonify({"items": services().knowledge_store.get_relations(entry_id)})


@api.post("/knowledge/relations")
def create_knowledge_relation():
    try:
        payload = KnowledgeRelation.model_validate(request.get_json(silent=True) or {})
    except ValidationError as error:
        return jsonify({"error": "关联无效", "details": error.errors()}), 400
    rid = services().knowledge_store.add_relation(
        payload.source_id, payload.target_id, payload.relation_type,
    )
    return jsonify({"id": rid}), 201


@api.post("/knowledge/<entry_id>/feedback")
def add_knowledge_feedback(entry_id: str):
    try:
        payload = KnowledgeFeedback.model_validate(request.get_json(silent=True) or {})
    except ValidationError as error:
        return jsonify({"error": "反馈无效", "details": error.errors()}), 400
    services().knowledge_store.add_feedback(entry_id, payload.feedback)
    return jsonify({"entry_id": entry_id})


@api.get("/knowledge-stats")
def knowledge_stats():
    project_id = request.args.get("project_id", "")
    return jsonify(services().knowledge_store.stats(project_id=project_id))


@api.post("/knowledge/cleanup")
def cleanup_knowledge():
    count = services().knowledge_store.cleanup()
    return jsonify({"cleaned": count})


# ==================== 项目管理 ====================

@api.get("/projects")
def list_projects():
    return jsonify({"items": services().project_manager.list_projects()})


@api.post("/projects")
def create_project():
    try:
        payload = CreateProjectRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as error:
        return jsonify({"error": "项目参数无效", "details": error.errors()}), 400
    try:
        project = services().project_manager.create_project(
            payload.name, payload.root_dir, payload.description,
        )
        return jsonify(project), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@api.get("/projects/<project_id>")
def get_project(project_id: str):
    project = services().project_manager.get_project(project_id)
    if not project:
        return jsonify({"error": "项目不存在"}), 404
    return jsonify(project)


@api.delete("/projects/<project_id>")
def delete_project(project_id: str):
    if not services().project_manager.delete_project(project_id):
        return jsonify({"error": "项目不存在"}), 404
    return "", 204


@api.get("/projects/<project_id>/agents")
def list_project_agents(project_id: str):
    return jsonify({"items": services().project_manager.list_agents(project_id)})


@api.post("/projects/<project_id>/agents")
def add_project_agent(project_id: str):
    data = request.get_json(silent=True) or {}
    template_id = data.get("template_id", "")
    if not template_id:
        return jsonify({"error": "需要指定 template_id"}), 400
    try:
        agent = services().project_manager.add_agent(
            project_id, template_id,
            sub_dir=data.get("sub_dir", ""),
            custom_prompt=data.get("system_prompt", ""),
            display_name=data.get("display_name", ""),
        )
        return jsonify(agent), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@api.put("/projects/<project_id>/agents/<agent_id>")
def update_project_agent(project_id: str, agent_id: str):
    payload = request.get_json(silent=True) or {}
    result = services().project_manager.update_agent(project_id, agent_id, payload)
    if not result:
        return jsonify({"error": "Agent 不存在"}), 404
    services().executor.registry.invalidate(project_id)
    return jsonify(result)


@api.delete("/projects/<project_id>/agents/<agent_id>")
def delete_project_agent(project_id: str, agent_id: str):
    try:
        ok = services().project_manager.delete_agent(project_id, agent_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if not ok:
        return jsonify({"error": "Agent 不存在"}), 404
    services().executor.registry.invalidate(project_id)
    return "", 204


# ==================== 模板管理 ====================

@api.get("/templates")
def list_templates():
    category = request.args.get("category")
    return jsonify({"items": services().project_manager.list_templates(category)})


@api.post("/templates")
def create_template():
    try:
        payload = AgentTemplate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as error:
        return jsonify({"error": "模板参数无效", "details": error.errors()}), 400
    tid = services().project_manager.create_template(payload.model_dump())
    return jsonify(tid), 201


@api.put("/templates/<template_id>")
def update_template(template_id: str):
    """更新 Agent 模板，后续从该模板创建的 Agent 将使用新配置。"""
    data = request.get_json(silent=True) or {}
    result = services().project_manager.update_template(template_id, data)
    if not result:
        return jsonify({"error": "模板不存在"}), 404
    return jsonify(result)


@api.delete("/templates/<template_id>")
def delete_template(template_id: str):
    """删除非内置模板。"""
    try:
        ok = services().project_manager.delete_template(template_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if not ok:
        return jsonify({"error": "模板不存在"}), 404
    return "", 204


# ==================== 模板中心 ====================

@api.get("/template-center")
def template_center():
    """返回所有 Agent 模板和 Skill 模板。"""
    agent_templates = services().project_manager.list_templates()
    skill_templates = []
    with services().store._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM skill_templates ORDER BY category, name"
        ).fetchall()
        skill_templates = [dict(r) for r in rows]
    return jsonify({"agents": agent_templates, "skills": skill_templates})


@api.post("/template-center/skills")
def publish_skill_template():
    """将项目 Skill 发布为公共模板。"""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    display_name = data.get("display_name", name)
    description = data.get("description", "")
    content = data.get("content", "")
    category = data.get("category", "general")
    if not name or not content:
        return jsonify({"error": "name 和 content 为必填项"}), 400
    import uuid as _uuid
    tid = _uuid.uuid4().hex
    with services().store._connect() as conn:
        conn.execute(
            "INSERT INTO skill_templates(id, name, display_name, description, category, content) VALUES (?,?,?,?,?,?)",
            (tid, name, display_name, description, category, content),
        )
    return jsonify({"id": tid}), 201


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
