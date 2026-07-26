import asyncio
import threading

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from app.agents.claude_executor import ClaudeAgentExecutor
from app.agents.registry import AgentProfile
from app.config import Settings
from app.domain.models import DagTask


def result_message(**updates) -> ResultMessage:
    values = {
        "subtype": "success",
        "duration_ms": 10,
        "duration_api_ms": 8,
        "is_error": True,
        "num_turns": 1,
        "session_id": "session-1",
    }
    values.update(updates)
    return ResultMessage(**values)


def test_result_error_prefers_assistant_api_error_over_success_subtype():
    detail = ClaudeAgentExecutor._result_error_detail(
        result_message(),
        ["API Error: Connection closed mid-response. The response above may be incomplete."],
    )

    assert detail == (
        "API Error: Connection closed mid-response. "
        "The response above may be incomplete."
    )


def test_result_error_reports_http_status_when_available():
    detail = ClaudeAgentExecutor._result_error_detail(
        result_message(api_error_status=529),
        [],
    )

    assert detail == "Claude API HTTP 529"


def test_result_error_never_reports_success_as_the_error():
    detail = ClaudeAgentExecutor._result_error_detail(result_message(), [])

    assert detail == "Claude API 请求中断或上游服务返回异常"


def test_connection_closed_error_is_transient():
    assert ClaudeAgentExecutor._is_transient_error(
        "API Error: Connection closed mid-response. The response above may be incomplete."
    )


def test_retryable_api_status_is_transient_without_matching_text():
    assert ClaudeAgentExecutor._is_transient_error("Claude API HTTP 529", 529)


def test_authentication_error_is_not_transient():
    assert not ClaudeAgentExecutor._is_transient_error(
        "API Error: authentication failed",
        401,
    )


def test_live_execution_resumes_same_session_after_transient_error(
    monkeypatch,
    tmp_path,
):
    calls = []
    emitted = []

    async def fake_query(*, prompt, options):
        calls.append((prompt, options))
        if len(calls) == 1:
            yield AssistantMessage(
                content=[TextBlock(
                    "API Error: Connection closed mid-response. "
                    "The response above may be incomplete."
                )],
                model="test-model",
            )
            yield result_message(
                session_id="3d8f1ee7-a56e-4ff5-966f-307c89e94a8d",
            )
            return
        yield AssistantMessage(
            content=[TextBlock('{"status":"completed","summary":"恢复完成"}')],
            model="test-model",
        )
        yield result_message(
            is_error=False,
            session_id="3d8f1ee7-a56e-4ff5-966f-307c89e94a8d",
        )

    class Registry:
        config_reader = None

        @staticmethod
        def get(project_id, agent_name):
            return AgentProfile(
                name=agent_name,
                agent_type="claude",
                prompt="测试",
            )

    class Events:
        @staticmethod
        def emit(run_id, event_type, **kwargs):
            emitted.append((event_type, kwargs))

    monkeypatch.setattr("app.agents.claude_executor.query", fake_query)
    executor = ClaudeAgentExecutor(
        Settings(anthropic_api_key="test", workspace_root=tmp_path),
        Registry(),
        Events(),
    )
    task = DagTask(
        id="retry-node",
        title="恢复测试",
        objective="验证连接中断后续接原会话",
        agent="backend",
    )

    result = asyncio.run(
        executor._execute_live(
            "run-1",
            task,
            [],
            threading.Event(),
            tmp_path,
            max_turns=3,
            timeout_seconds=10,
        )
    )

    assert result.status == "completed"
    assert result.summary == "恢复完成"
    assert len(calls) == 2
    assert calls[0][1].resume is None
    assert calls[0][1].permission_mode == "auto"
    assert calls[0][1].allowed_tools == []
    assert calls[1][1].resume == "3d8f1ee7-a56e-4ff5-966f-307c89e94a8d"
    prompt_events = [item for item in emitted if item[0] == "agent.prompt"]
    assert prompt_events[0][1]["payload"]["sdk_permission_mode"] == "auto"
    retry_events = [item for item in emitted if item[0] == "agent.retrying"]
    assert len(retry_events) == 1
    assert retry_events[0][1]["payload"]["resume_session"] is True
