"""The invoice agent as a LangGraph state machine.

    START -> extract --(ok)--> reconcile -> decide --(approve)--> persist -> END
                     \\--(unreadable)----------^   \\--(other)--> investigate --^

Why LangGraph and not a plain function: each node is checkpointed (thread =
invoice id), so a crash after the expensive extraction resumes from there
instead of paying the LLM again; branches are explicit and the graph can be
rendered for documentation.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from opsagent.agent.deps import AgentDeps
from opsagent.agent.nodes import Nodes
from opsagent.agent.state import AgentState


def build_graph(
    deps: AgentDeps, checkpointer: BaseCheckpointSaver[str] | None = None
) -> CompiledStateGraph[AgentState]:
    nodes = Nodes(deps)
    graph = StateGraph(AgentState)
    graph.add_node("extract", nodes.extract)
    graph.add_node("reconcile", nodes.reconcile)
    graph.add_node("decide", nodes.decide)
    graph.add_node("investigate", nodes.investigate)
    graph.add_node("persist", nodes.persist)

    graph.add_edge(START, "extract")
    graph.add_conditional_edges(
        "extract", nodes.route_after_extract, {"reconcile": "reconcile", "decide": "decide"}
    )
    graph.add_edge("reconcile", "decide")
    graph.add_conditional_edges(
        "decide", nodes.route_after_decide, {"persist": "persist", "investigate": "investigate"}
    )
    graph.add_edge("investigate", "persist")
    graph.add_edge("persist", END)
    return graph.compile(checkpointer=checkpointer, name="invoice-agent")
