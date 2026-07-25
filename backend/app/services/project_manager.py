"""多项目管理 + Agent 模板 + 项目 Agent CRUD。"""

from __future__ import annotations

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
        "id": "code-reviewer-template",
        "name": "code-reviewer",
        "display_name": "代码审查",
        "description": "专注代码质量审查、最佳实践检查、代码异味识别和重构建议",
        "category": "quality",
        "agent_type": "claude",
        "default_sub_dir": "",
        "default_prompt": "你是专业代码审查专家。你的职责是审查代码质量，不做实现开发。\n\n审查要点：\n1. 代码结构和组织\n2. 错误处理和边界条件\n3. 性能问题和优化建议\n4. 安全漏洞（SQL注入、XSS等）\n5. 命名规范和可读性\n6. 测试覆盖和可测试性\n7. 依赖管理和版本兼容性\n\n输出格式：每个问题标注严重程度（严重/重要/建议）、位置、说明和修复建议。严格只读，不修改任何文件。",
        "default_tools": ["Read", "Glob", "Grep"],
        "default_skills": [],
        "is_builtin": 1,
    },
    {
        "id": "doc-diff-template",
        "name": "doc-diff",
        "display_name": "文档对比",
        "description": "对比文档和接口差异，检测 API 变更、配置漂移、文档不一致",
        "category": "quality",
        "agent_type": "claude",
        "default_sub_dir": "",
        "default_prompt": "你是文档和接口对比专家。对比文档与实现差异，不做代码修改。\n\n对比场景：\n1. API 文档 vs 实际实现\n2. 前后端接口定义差异\n3. 配置文件差异和环境漂移\n4. 多版本分支间的变更审查\n5. README vs 实际代码行为\n6. OpenAPI/Swagger 规范一致性\n\n输出格式：每个差异标注类别、文件位置、当前状态、期望状态和影响范围。严格只读。",
        "default_tools": ["Read", "Glob", "Grep", "Bash"],
        "default_skills": [],
        "is_builtin": 1,
    },
    {
        "id": "api-designer-template",
        "name": "api-designer",
        "display_name": "接口设计",
        "description": "专注 RESTful API 设计、接口契约定义、数据模型设计和 API 文档生成",
        "category": "design",
        "agent_type": "claude",
        "default_sub_dir": "",
        "default_prompt": "你是 API 和接口设计专家。设计清晰一致的 RESTful API 和数据模型。\n\n设计原则：\n1. RESTful 资源命名和路由设计\n2. 请求/响应数据模型定义\n3. 错误码和错误响应规范\n4. 认证和授权接口设计\n5. 分页、过滤、排序标准\n6. 版本管理策略\n7. OpenAPI/Swagger 规范输出\n\n输出格式：每个接口包含方法、路径、请求体、响应体、错误码和示例。需要写代码时先输出设计方案等待确认。",
        "default_tools": ["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        "default_skills": [],
        "is_builtin": 1,
    },
]


class ProjectManager:
    """项目 + Agent 管理。文件优先，DB 为缓存。"""

    def __init__(self, store: SQLiteStore, config_reader: Any = None) -> None:
        self.store = store
        self.config_reader = config_reader
        self._seed_templates()

    def _seed_templates(self) -> None:
        """首次启动时将内置模板写入 templates/agents/。"""
        tmpl_dir = self.config_reader.workspace_root / "templates" / "agents"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        for tmpl in BUILTIN_TEMPLATES:
            yaml_file = tmpl_dir / f"{tmpl['name']}.yaml"
            if not yaml_file.exists():
                data = {
                    "id": tmpl["id"],
                    "name": tmpl["name"],
                    "display_name": tmpl["display_name"],
                    "description": tmpl["description"],
                    "category": tmpl.get("category", "other"),
                    "agent_type": tmpl["agent_type"],
                    "sub_dir": tmpl.get("default_sub_dir", ""),
                    "system_prompt": tmpl["default_prompt"],
                    "tools": tmpl["default_tools"],
                    "skills": tmpl.get("default_skills", []),
                    "sort_order": tmpl.get("sort_order", 0),
                }
                import yaml
                yaml_file.write_text(
                    yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )

    # ── 项目 CRUD (file-backed) ──

    def create_project(self, name: str, root_dir: str, description: str = "") -> dict:
        root = Path(root_dir).resolve()
        if not root.is_dir():
            raise ValueError(f"目录不存在: {root}")
        # 生成项目 ID，创建 .workspace/<id>/ 目录
        project_id = uuid.uuid4().hex
        data = {"id": project_id, "name": name, "description": description, "root_dir": str(root)}
        if self.config_reader:
            project_cfg = self.config_reader.for_project(project_id)
            project_cfg.save_project(data)
            # 确保项目目录结构存在
            project_cfg._ensure_dirs()
        return data

    def delete_project(self, project_id: str) -> bool:
        if self.config_reader:
            return self.config_reader.delete_project(project_id)
        return False

    def list_projects(self) -> list[dict]:
        if self.config_reader:
            return self.config_reader.list_projects()
        return []

    def get_project(self, project_id: str) -> dict | None:
        if self.config_reader:
            try:
                project_cfg = self.config_reader.for_project(project_id)
                return project_cfg.load_project()
            except Exception:
                pass
        return None

    # ── Agent CRUD (file-backed) ──

    def add_agent(self, project_id: str, template_id: str = "", sub_dir: str = "",
                  custom_prompt: str = "", display_name: str = "",
                  name: str = "", agent_type: str = "",
                  tools: list | None = None, skills: list | None = None,
                  description: str = "", model: str = "") -> dict | None:
        """创建 Agent YAML 文件。可从模板创建，也可手动创建。"""
        if not self.config_reader:
            return None

        project_cfg = self.config_reader.for_project(project_id)
        # 确保项目目录存在
        project_cfg._ensure_dirs()

        if template_id:
            # 从模板创建
            templates = self.config_reader.list_agent_templates()
            tmpl = None
            for t in templates:
                if t.get("id") == template_id or t.get("name") == template_id:
                    tmpl = t
                    break
            if not tmpl:
                raise ValueError(f"模板不存在: {template_id}")

            agent_name = tmpl["name"]
            data = {
                "name": agent_name,
                "display_name": display_name or tmpl.get("display_name", agent_name),
                "description": tmpl.get("description", ""),
                "agent_type": tmpl.get("agent_type", "claude"),
                "sub_dir": sub_dir or tmpl.get("sub_dir", ""),
                "system_prompt": custom_prompt or tmpl.get("system_prompt", ""),
                "tools": tools if tools is not None else tmpl.get("tools", []),
                "skills": skills if skills is not None else tmpl.get("skills", []),
                "sort_order": 0,
                "model": model or tmpl.get("model", ""),
            }
        else:
            # 手动创建（无模板）
            if not name:
                raise ValueError("手动创建需要指定 name")
            if not agent_type:
                agent_type = "claude"
            data = {
                "name": name,
                "display_name": display_name or name,
                "description": description or "",
                "agent_type": agent_type,
                "sub_dir": sub_dir or "",
                "system_prompt": custom_prompt or "",
                "tools": tools or [],
                "skills": skills or [],
                "sort_order": 0,
                "model": model or "",
            }
        project_cfg.save_agent(data["name"], data)
        return data

    def update_agent(self, project_id: str, agent_id: str, updates: dict) -> dict | None:
        if not self.config_reader:
            return None
        project_cfg = self.config_reader.for_project(project_id)
        try:
            existing = project_cfg.get_agent(agent_id)
        except Exception:
            return None
        allowed = {"display_name", "description", "system_prompt", "tools",
                   "skills", "sub_dir", "sort_order", "model"}
        for k, v in updates.items():
            if k in allowed and v is not None:
                existing[k] = v
        project_cfg.save_agent(agent_id, existing)
        return existing

    def delete_agent(self, project_id: str, agent_id: str) -> bool:
        if not self.config_reader:
            return False
        project_cfg = self.config_reader.for_project(project_id)
        try:
            project_cfg.delete_agent(agent_id)
            return True
        except Exception:
            return False

    def list_agents(self, project_id: str) -> list[dict]:
        if self.config_reader:
            project_cfg = self.config_reader.for_project(project_id)
            return project_cfg.list_agents()
        return []

    # ── 模板管理 (file-backed) ──

    def list_templates(self, category: str | None = None) -> list[dict]:
        """列出全局模板目录中的 Agent 模板（文件优先）。"""
        if self.config_reader:
            all_tmpl = self.config_reader.list_agent_templates()
            if category:
                return [t for t in all_tmpl if t.get("category") == category]
            return all_tmpl
        return []

    def create_template(self, data: dict) -> dict | None:
        """模板只读 — 用户直接在 templates/agents/ 编辑 YAML 文件。"""
        return {"id": data.get("name", ""), "note": "请直接在 templates/agents/ 编辑模板 YAML"}

    def update_template(self, template_id: str, updates: dict) -> dict | None:
        """模板只读 — 用户直接在 templates/agents/ 编辑 YAML 文件。"""
        return {"id": template_id, "note": "请直接在 templates/agents/ 编辑模板 YAML"}

    def delete_template(self, template_id: str) -> bool:
        """模板只读 — 用户直接在 templates/agents/ 删除 YAML 文件。"""
        return True