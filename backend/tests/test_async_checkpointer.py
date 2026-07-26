import asyncio
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.run_manager import _ainvoke_graph


class CounterState(TypedDict):
    value: int


def test_async_graph_uses_async_sqlite_checkpointer(tmp_path: Path):
    checkpoint_path = tmp_path / "checkpoints.db"

    def graph_factory(checkpointer):
        builder = StateGraph(CounterState)
        builder.add_node("increment", lambda state: {"value": state["value"] + 1})
        builder.add_edge(START, "increment")
        builder.add_edge("increment", END)
        return builder.compile(checkpointer=checkpointer)

    result = asyncio.run(
        _ainvoke_graph(
            graph_factory,
            checkpoint_path,
            {"value": 1},
            {"configurable": {"thread_id": "rag-checkpoint-test"}},
        )
    )

    assert result["value"] == 2
    assert checkpoint_path.is_file()
