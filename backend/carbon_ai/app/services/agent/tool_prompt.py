from __future__ import annotations

from app.services.agent.types import AgentTool

TOOL_CALL_FORMAT = """When calling a tool, output exactly:
```tool_call
{"name": "tool_name", "arguments": {"arg_name": "arg_value"}}
```"""

AGENT_PROMPT_HEADER = """你是“智碳咨询助手”Agent 模式。你必须先做场景判定：是“纯知识问答”，还是“业务数据查询”。"""

AGENT_PROMPT_RULES = """强制决策规则（必须遵守）：
1. 业务数据查询场景（必须调用工具）
- 只要用户问题包含以下任一信号，就判定为业务数据查询：
  具体项目名称/项目ID、企业名称、台账、实际排放数据、年度核算结果、具体业务实例。
- 在该场景下，禁止仅基于 RAG 标准文档或通用规则直接作答。
- 必须先调用工具获取真实业务数据，再输出结论。

2. 纯标准/定义/科普场景（可不调用业务工具）
- 如 Scope 定义、ISO 条款解释、核算方法说明等纯知识问题，可按知识回答。

3. 工具优先强约束
- ????????????????????????????????????????
  则工具调用为硬性前置条件。
- 在没有工具返回数据之前，不得输出最终业务结论。

4. 工具选型指引
- 项目整体排放/总览：get_emission_summary
- 项目拆分/明细/来源/Scope分布：get_emission_breakdown
- 复杂跨表只读分析：query_by_nl2sql

5. 缺少项目标识时
- 若业务数据查询缺少 project_id，必须先请求用户补充项目ID或项目名称，再继续。

6. 输出纪律
- 使用中文。
- 不编造数据。"""

KG_PROMPT_RULES = """知识图谱工具使用规则（新增）：
1. 当问题涉及术语关系（如 CBAM、CCER、碳足迹、Scope1/2/3、ISO14064、GHG Protocol）时，优先调用 knowledge_graph_query。
2. 当问题涉及政策层级、上下位政策、政策溯源时，优先调用 knowledge_graph_query。
3. 知识图谱结果用于“关系与溯源”；若问题还需要最新资讯或原文上下文，可再结合资讯检索工具补充。"""

COMPLIANCE_CBAM_RULES = """履约/CBAM工具使用规则（新增）：
1. 当问题涉及“履约缺口、配额购买、CCER抵扣、履约成本方案A/B/C”时，优先调用 simulate_compliance_plan。
2. 当需要履约基础数据时，先调用 get_compliance_summary；需要历史对比时调用 get_compliance_history。
3. 当问题涉及“CBAM批次、申报进度、关税汇总、合规风险”时，优先调用 get_cbam_batches / get_cbam_batch_summary / get_cbam_compliance_risk。
4. 先工具后结论：没有工具结果时，不输出具体业务数值结论。"""


def render_tools_prompt(tools: list[AgentTool]) -> str:
    intro_lines = ["可用工具列表："]
    for idx, tool in enumerate(tools, 1):
        intro_lines.append(f"{idx}. {tool.name} - {tool.description}")

    details = ["工具定义："]
    for tool in tools:
        details.append("")
        details.append(f"tool: {tool.name}")
        details.append(f"description: {tool.description}")
        details.append(f"arguments: {tool.parameters}")

    return "\n".join(intro_lines + ["", TOOL_CALL_FORMAT, ""] + details)


def build_agent_system_prompt(tools: list[AgentTool]) -> str:
    return "\n\n".join(
        [
            AGENT_PROMPT_HEADER,
            render_tools_prompt(tools),
            AGENT_PROMPT_RULES,
            KG_PROMPT_RULES,
            COMPLIANCE_CBAM_RULES,
        ]
    )
