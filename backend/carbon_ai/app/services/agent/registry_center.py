from __future__ import annotations

from app.services.agent.registry import AgentToolRegistry
from app.services.agent.tools import (
    build_cbam_batch_summary_tool,
    build_cbam_batches_tool,
    build_cbam_risk_tool,
    build_compliance_history_tool,
    build_compliance_simulate_tool,
    build_compliance_summary_tool,
    build_emission_breakdown_tool,
    build_emission_summary_tool,
    build_knowledge_graph_tool,
    build_nl2sql_tool,
    build_project_info_tool,
)


def build_default_registry() -> AgentToolRegistry:
    registry = AgentToolRegistry()
    registry.register(build_project_info_tool())
    registry.register(build_emission_summary_tool())
    registry.register(build_emission_breakdown_tool())
    registry.register(build_nl2sql_tool())
    registry.register(build_knowledge_graph_tool())
    registry.register(build_compliance_summary_tool())
    registry.register(build_compliance_simulate_tool())
    registry.register(build_compliance_history_tool())
    registry.register(build_cbam_batches_tool())
    registry.register(build_cbam_batch_summary_tool())
    registry.register(build_cbam_risk_tool())
    return registry
