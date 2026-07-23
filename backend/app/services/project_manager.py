"""多项目管理 + Agent 模板 + 项目 Agent CRUD。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.storage.sqlite_store import SQLiteStore


# 内置 Agent 模板
BUILTIN_TEMPLATES = [
    {
        "id": "brain-template",
        "name": "brain",
        "display_name": "DeepSeek 主脑",
        "description": "任务规划、契约设计、DAG生成、最终验收",
        "category": "other",
        "agent_type": "brain",
        "default_sub_dir": "",
        "default_prompt": "你是项目主脑，负责分析用户目标、制定任务计划、生成 DAG 并验收结果。",
        "default_tools": [],
        "default_skills": [],
        "is_builtin": 1,
    },
    {
        "id": "rag-template",
        "name": "rag",
        "display_name": "RAG",
        "description": "基于 LangChain 的知识检索与录入 Agent，由 RAGAgentExecutor 驱动",
        "category": "other",
        "agent_type": "rag",
        "default_sub_dir": "",
        "default_prompt": "你是知识库管理 Agent，负责检索知识库、录入新知识和建立知识关联。使用 search_knowledge 检索、add_knowledge 录入、get_knowledge 查看详情、list_knowledge 浏览条目。优先从知识库检索相关信息，综合后回答。",
        "default_tools": [],
        "default_skills": [],
        "is_builtin": 1,
    },
    {
        "id": "vue-frontend-template",
        "name": "vue-frontend",
        "display_name": "Vue 前端",
        "description": "Vue 3 + TypeScript + Vite，组件化开发，状态管理，前端测试",
        "category": "frontend",
        "agent_type": "claude",
        "default_sub_dir": "frontend",
        "default_prompt": "你是 Vue 3 前端开发专家。使用 TypeScript、Vite 构建工具，遵循 Vue 3 Composition API 规范。负责页面组件、路由、状态管理和前端测试。\n\n工具使用：CLI 命令前加 rtk 前缀可节省 token（如 rtk npm test）。Read 工具只读取需要的文件片段，避免全文读取大文件。输出简洁，只包含关键信息。",
        "default_tools": ["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        "default_skills": [],
        "is_builtin": 1,
    },
    {
        "id": "react-frontend-template",
        "name": "react-frontend",
        "display_name": "React 前端",
        "description": "React + TypeScript，Hooks，React Router，前端测试",
        "category": "frontend",
        "agent_type": "claude",
        "default_sub_dir": "frontend",
        "default_prompt": "你是 React 前端开发专家。使用 TypeScript、React Hooks、React Router。负责组件开发、状态管理、路由配置和前端测试。\n\n工具使用：CLI 命令前加 rtk 前缀可节省 token。Read 只读取需要的文件片段。输出简洁。",
        "default_tools": ["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        "default_skills": [],
        "is_builtin": 1,
    },
    {
        "id": "flask-backend-template",
        "name": "flask-backend",
        "display_name": "Flask 后端",
        "description": "Python Flask API 服务，ORM，RESTful 设计，后端测试",
        "category": "backend",
        "agent_type": "claude",
        "default_sub_dir": "backend",
        "default_prompt": "你是 Python Flask 后端开发专家。负责 REST API 设计、数据库 ORM、业务逻辑、认证授权和后端测试。遵循 Flask 最佳实践。\n\n工具使用：CLI 命令前加 rtk 前缀（如 rtk pytest）。Read 只读取需要的文件片段。输出简洁。",
        "default_tools": ["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        "default_skills": [],
        "is_builtin": 1,
    },
    {
        "id": "springboot-backend-template",
        "name": "springboot-backend",
        "display_name": "SpringBoot 后端",
        "description": "Java SpringBoot REST API，JPA，Spring Security，JUnit 测试",
        "category": "backend",
        "agent_type": "claude",
        "default_sub_dir": "backend",
        "default_prompt": "你是 Java SpringBoot 后端开发专家。负责 REST API、JPA 持久化、Spring Security 认证、业务逻辑和 JUnit 测试。遵循 Spring 最佳实践。",
        "default_tools": ["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        "default_skills": [],
        "is_builtin": 1,
    },
    {
        "id": "springboot-netty-template",
        "name": "springboot-netty",
        "display_name": "Netty 数据服务",
        "description": "Java Netty TCP/UDP 数据接收、协议解析、编码发送",
        "category": "netty",
        "agent_type": "claude",
        "default_sub_dir": "netty",
        "default_prompt": "你是 Java Netty 数据传输专家。负责 TCP/UDP 连接管理、数据接收、粘包拆包处理、协议编解码、ByteBuf 管理和传输层测试。",
        "default_tools": ["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        "default_skills": [],
        "is_builtin": 1,
    },
    {
        "id": "deepseek-agent-template",
        "name": "deepseek-agent",
        "display_name": "DeepSeek 编码 Agent",
        "description": "基于 LangChain 的 DeepSeek 通用 Agent，支持工具调用和代码生成",
        "category": "backend",
        "agent_type": "deepseek",
        "default_sub_dir": "",
        "default_prompt": "你是 DeepSeek 编程助手，负责代码实现、调试、测试和文档编写。使用可用的工具自主完成任务，结束时简洁说明结果、修改文件和验证情况。",
        "default_tools": ["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        "default_skills": [],
        "is_builtin": 1,
    },
]


class ProjectManager:
    """项目 + Agent 管理。"""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self._seed_templates()

    def _seed_templates(self) -> None:
        """首次启动时创建内置模板。"""
        with self.store._connect() as conn:
            existing = conn.execute("SELECT COUNT(*) as cnt FROM agent_templates").fetchone()
            if existing["cnt"] > 0:
                return
            for tmpl in BUILTIN_TEMPLATES:
                conn.execute(
                    """INSERT OR IGNORE INTO agent_templates(
                        id, name, display_name, description, category, agent_type,
                        default_sub_dir, default_prompt, default_tools, default_skills, is_builtin
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        tmpl["id"], tmpl["name"], tmpl["display_name"], tmpl["description"],
                        tmpl["category"], tmpl["agent_type"], tmpl["default_sub_dir"],
                        tmpl["default_prompt"],
                        json.dumps(tmpl["default_tools"], ensure_ascii=False),
                        json.dumps(tmpl["default_skills"], ensure_ascii=False),
                        tmpl["is_builtin"],
                    ),
                )

    # ── 项目 CRUD ──

    def create_project(self, name: str, root_dir: str, description: str = "") -> dict:
        root = Path(root_dir).resolve()
        if not root.is_dir():
            raise ValueError(f"目录不存在: {root}")

        pid = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self.store._connect() as conn:
            conn.execute(
                "INSERT INTO projects(id, name, root_dir, description, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (pid, name, str(root), description, now, now),
            )
        return self.get_project(pid) or {}

    def delete_project(self, project_id: str) -> bool:
        with self.store._connect() as conn:
            cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return cursor.rowcount > 0

    def list_projects(self) -> list[dict]:
        with self.store._connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get_project(self, project_id: str) -> dict | None:
        with self.store._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    # ── Agent CRUD ──

    def add_agent(self, project_id: str, template_id: str, sub_dir: str = "",
                  custom_prompt: str = "", display_name: str = "") -> dict | None:
        with self.store._connect() as conn:
            tmpl = conn.execute("SELECT * FROM agent_templates WHERE id = ?", (template_id,)).fetchone()
            if not tmpl:
                raise ValueError(f"模板不存在: {template_id}")
            tmpl = dict(tmpl)

            name_base = tmpl["name"]
            name = name_base
            suffix = 2
            while conn.execute(
                "SELECT id FROM project_agents WHERE project_id = ? AND name = ?", (project_id, name)
            ).fetchone():
                name = f"{name_base}-{suffix}"
                suffix += 1

            aid = uuid.uuid4().hex
            conn.execute(
                """INSERT INTO project_agents(id, project_id, name, display_name, description, template_id,
                agent_type, sub_dir, system_prompt, tools, skills, is_required, sort_order)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    aid, project_id, name,
                    display_name or tmpl["display_name"],
                    tmpl["description"],
                    template_id,
                    tmpl["agent_type"],
                    sub_dir or tmpl["default_sub_dir"],
                    custom_prompt or tmpl["default_prompt"],
                    tmpl["default_tools"],
                    tmpl["default_skills"],
                    0,  # claude agents are not required
                    99,  # default sort_order
                ),
            )
        return dict(conn.execute(
            "SELECT * FROM project_agents WHERE id = ?", (aid,)
        ).fetchone())

    def update_agent(self, project_id: str, agent_id: str, updates: dict) -> dict | None:
        allowed = {"display_name", "description", "system_prompt", "tools",
                   "skills", "sub_dir", "sort_order"}
        fields = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if not fields:
            return None
        if "tools" in fields and not isinstance(fields["tools"], str):
            fields["tools"] = json.dumps(fields["tools"], ensure_ascii=False)
        if "skills" in fields and not isinstance(fields["skills"], str):
            fields["skills"] = json.dumps(fields["skills"], ensure_ascii=False)
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        set_clause += ", updated_at = ?"
        values = list(fields.values()) + [datetime.now(timezone.utc).isoformat(), agent_id, project_id]
        with self.store._connect() as conn:
            cursor = conn.execute(
                f"UPDATE project_agents SET {set_clause} WHERE id = ? AND project_id = ?",
                values,
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM project_agents WHERE id = ?", (agent_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_agent(self, project_id: str, agent_id: str) -> bool:
        with self.store._connect() as conn:
            # 检查是否为必选 Agent
            row = conn.execute(
                "SELECT is_required FROM project_agents WHERE id = ? AND project_id = ?",
                (agent_id, project_id),
            ).fetchone()
            if not row:
                return False
            if row["is_required"]:
                raise ValueError("必选 Agent 不可删除")
            cursor = conn.execute(
                "DELETE FROM project_agents WHERE id = ? AND project_id = ?",
                (agent_id, project_id),
            )
        return cursor.rowcount > 0

    def list_agents(self, project_id: str) -> list[dict]:
        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM project_agents WHERE project_id = ? ORDER BY sort_order",
                (project_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── 模板管理 ──

    def list_templates(self, category: str | None = None) -> list[dict]:
        with self.store._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM agent_templates WHERE category = ? ORDER BY name",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_templates ORDER BY category, name"
                ).fetchall()
        results = []
        for row in rows:
            r = dict(row)
            r["default_tools"] = json.loads(r.get("default_tools", "[]"))
            r["default_skills"] = json.loads(r.get("default_skills", "[]"))
            results.append(r)
        return results

    def create_template(self, data: dict) -> dict | None:
        tid = data.get("id") or uuid.uuid4().hex
        with self.store._connect() as conn:
            conn.execute(
                """INSERT INTO agent_templates(
                    id, name, display_name, description, category, agent_type,
                    default_sub_dir, default_prompt, default_tools, default_skills, is_builtin
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    tid,
                    data["name"],
                    data.get("display_name", data["name"]),
                    data.get("description", ""),
                    data.get("category", "general"),
                    data.get("agent_type", "claude"),
                    data.get("default_sub_dir", ""),
                    data.get("default_prompt", ""),
                    json.dumps(data.get("default_tools", []), ensure_ascii=False),
                    json.dumps(data.get("default_skills", []), ensure_ascii=False),
                    0,  # 用户创建的模板不是内置模板
                ),
            )
        return {"id": tid}

    def update_template(self, template_id: str, updates: dict) -> dict | None:
        """更新模板配置，后续从该模板创建的 Agent 将使用新默认值。"""
        allowed = {"display_name", "description", "default_sub_dir",
                   "default_prompt", "default_tools", "default_skills", "category"}
        fields = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if not fields:
            return None
        if "default_tools" in fields and not isinstance(fields["default_tools"], str):
            fields["default_tools"] = json.dumps(fields["default_tools"], ensure_ascii=False)
        if "default_skills" in fields and not isinstance(fields["default_skills"], str):
            fields["default_skills"] = json.dumps(fields["default_skills"], ensure_ascii=False)
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [template_id]
        with self.store._connect() as conn:
            cursor = conn.execute(
                f"UPDATE agent_templates SET {set_clause} WHERE id = ?", values
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM agent_templates WHERE id = ?", (template_id,)
            ).fetchone()
        if not row:
            return None
        r = dict(row)
        r["default_tools"] = json.loads(r.get("default_tools", "[]"))
        r["default_skills"] = json.loads(r.get("default_skills", "[]"))
        return r

    def delete_template(self, template_id: str) -> bool:
        """删除非内置模板。内置模板不可删除。"""
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT is_builtin FROM agent_templates WHERE id = ?", (template_id,)
            ).fetchone()
            if not row:
                return False
            if row["is_builtin"]:
                raise ValueError("内置模板不可删除")
            cursor = conn.execute(
                "DELETE FROM agent_templates WHERE id = ?", (template_id,)
            )
        return cursor.rowcount > 0