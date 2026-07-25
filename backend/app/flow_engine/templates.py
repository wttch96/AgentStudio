"""Jinja2 sandboxed template rendering for flow node prompts."""

from __future__ import annotations

from jinja2 import Environment, BaseLoader, Undefined
from jinja2.sandbox import SandboxedEnvironment

from app.domain.models import AgentResult


class SilentUndefined(Undefined):
    """Returns empty string for undefined variables instead of raising."""

    def __str__(self) -> str:
        return ""

    def __getattr__(self, _name: str) -> "SilentUndefined":
        return SilentUndefined()

    def __getitem__(self, _key: str) -> "SilentUndefined":
        return SilentUndefined()

    def __call__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return ""


def _create_sandbox() -> Environment:
    env = SandboxedEnvironment(
        loader=BaseLoader(),
        autoescape=False,
        undefined=SilentUndefined,
    )
    # Keep default join, slice filters. Add a safe 'default' filter override.
    env.filters["default"] = lambda val, fallback="": val if val else fallback
    return env


_jinja_env = _create_sandbox()


class FlowTemplateRenderer:
    """Renders Jinja2 templates with input parameters and dependency results."""

    def __init__(self) -> None:
        self.env = _jinja_env

    def render_node(self, template: str, inputs: dict,
                    results: dict[str, AgentResult]) -> str:
        """Render a single node's objective template.

        Template context:
          - {{ input.key }}       — user-supplied parameters
          - {{ node_id.output.summary }}  — completed upstream node results
          - {{ node_id.output.changed_files }}
          - {{ node_id.output.status }}
          - {{ node_id.output.provides }}
          - {{ node_id.output.error }}
        """
        ctx = {"input": inputs}
        for node_id, result in results.items():
            ctx[node_id] = {
                "output": {
                    "summary": result.summary,
                    "changed_files": result.changed_files,
                    "status": result.status,
                    "provides": result.provides,
                    "error": result.error or "",
                }
            }
        return self.env.from_string(template).render(**ctx)

    def render_synthesize(self, template: str, inputs: dict,
                          results: dict[str, AgentResult]) -> str:
        """Render the final synthesize template.

        Context: {{ input }}, {{ results }} (full dict of node_id → AgentResult)
        """
        ctx = {
            "input": inputs,
            "results": {nid: r.model_dump() for nid, r in results.items()},
        }
        # Also add per-node shortcuts
        for node_id, result in results.items():
            ctx[node_id] = {
                "output": {
                    "summary": result.summary,
                    "changed_files": result.changed_files,
                    "status": result.status,
                    "provides": result.provides,
                    "error": result.error or "",
                }
            }
        return self.env.from_string(template).render(**ctx)
