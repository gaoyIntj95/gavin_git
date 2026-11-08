from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session

from app.models.emission_source import EmissionSource
from app.models.project import Project
from app.services.calculation_service import calculate_project_totals

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
FALLBACK_ENABLED = os.getenv("RAG_FALLBACK_ENABLED", "true").lower() == "true"


def get_project_info(db: Session, project_id: int) -> dict[str, Any]:
    project = db.query(Project).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not project:
        return {"error": f"项目 ID={project_id} 不存在"}
    return {
        "id": project.id,
        "name": project.name,
        "organization": project.organization,
        "industry": project.industry,
        "standard": project.standard,
        "boundary": project.boundary,
        "boundary_method": project.boundary_method,
        "base_year": project.base_year,
        "report_year": project.report_year,
        "calculation_profile": project.calculation_profile,
    }


def get_emission_summary(db: Session, project_id: int) -> dict[str, Any]:
    project = db.query(Project).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not project:
        return {"error": f"项目 ID={project_id} 不存在"}

    try:
        totals = calculate_project_totals(db, project_id)
    except Exception as exc:
        logger.error("Calculate project totals failed: %s", exc)
        return {"error": f"核算项目排放数据失败: {exc}"}

    sources = db.query(EmissionSource).filter(EmissionSource.project_id == project_id).all()
    top_sources = sorted(sources, key=lambda s: s.co2e, reverse=True)[:5]

    total_emission = totals.get("total_emission", 0)
    scope1 = totals.get("scope1_emission", 0)
    scope2 = totals.get("scope2_emission", 0)
    scope3 = totals.get("scope3_emission", 0)

    scope1_pct = round(scope1 / total_emission * 100, 1) if total_emission > 0 else 0
    scope2_pct = round(scope2 / total_emission * 100, 1) if total_emission > 0 else 0
    scope3_pct = round(scope3 / total_emission * 100, 1) if total_emission > 0 else 0

    return {
        "project_name": project.name,
        "total_emission": total_emission,
        "direct_emission": totals.get("direct_emission", 0),
        "indirect_emission": totals.get("indirect_emission", 0),
        "scope1_emission": scope1,
        "scope2_emission": scope2,
        "scope3_emission": scope3,
        "scope1_pct": scope1_pct,
        "scope2_pct": scope2_pct,
        "scope3_pct": scope3_pct,
        "calculation_profile": totals.get("calculation_profile", ""),
        "top_sources": [
            {
                "name": s.name,
                "category": s.category,
                "co2e": round(s.co2e, 4),
                "scope": s.scope,
            }
            for s in top_sources
        ],
        "source_count": len(sources),
    }


def execute_tool_call(db: Session, tool_name: str, arguments: dict) -> dict[str, Any]:
    if tool_name == "get_project_info":
        project_id = arguments.get("project_id")
        if project_id is None:
            return {"error": "缺少 project_id 参数"}
        return get_project_info(db, project_id)

    if tool_name == "get_emission_summary":
        project_id = arguments.get("project_id")
        if project_id is None:
            return {"error": "缺少 project_id 参数"}
        return get_emission_summary(db, project_id)

    return {"error": f"未知工具: {tool_name}"}


async def ask_with_agent_tools(
    question: str,
    project_id: int | None = None,
    db: Session | None = None,
    session_id: str = "default",
) -> tuple[str, list[str]]:
    """使用智能体工具回答问题"""
    if not db:
        raise ValueError("Database session not provided")

    current_user = {"id": 1, "username": "admin"}

    lower_q = question.lower()
    docs = []
    if project_id is not None:
        try:
            from app.services.vector_store import similarity_search
            docs = similarity_search(question, k=3)
        except Exception as exc:
            logger.warning("Vector search failed, proceeding without knowledge retrieval")
            docs = []
    
    context_parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.get("metadata", {}).get("source_file", "未知来源")
        context_parts.append(f"[文档{i}] 来源: {source}\n{doc['content']}")
    context_text = "\n\n".join(context_parts) if context_parts else "（未检索到相关文档）"

    user_content = f"用户问题：{question}\n\n参考知识：\n{context_text}"
    if project_id is not None:
        user_content += f"\n\n当前关联项目ID: {project_id}，如需查询项目数据请调用相应工具。"

    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    max_iterations = 3
    tool_results = []
    all_tool_names = [
        "get_compliance_analysis",
        "get_project_info",
        "get_emission_summary",
        "get_compliance_snapshots",
        "get_compliance_audit_trail",
        "get_compliance_recommendations",
        "get_cbam_batches",
        "get_cbam_batch_summary",
        "get_cbam_compliance_risk",
        "get_cbam_export_package_info",
        "get_cbam_export_status",
    ]

    for _ in range(max_iterations):
        try:
            import ollama

            client = ollama.Client(host=OLLAMA_BASE_URL)
            response = client.chat(
                model=OLLAMA_MODEL,
                messages=messages,
            )
            response_text = response.get("message", {}).get("content", "")

            tool_calls = _parse_tool_calls(response_text)

            if not tool_calls:
                if not tool_results:
                    return response_text, ["知识库检索"]

                references = []
                for doc in docs:
                    source = doc.get("metadata", {}).get("source_file", "")
                    if source and source not in references:
                        references.append(source)
                for tr in tool_results:
                    ref = f"业务数据查询: {tr.get('tool', '')}"
                    if ref not in references:
                        references.append(ref)
                return response_text, references

            for tc in tool_calls:
                tool_name = tc.get("name", "")
                arguments = tc.get("arguments", {})

                if tool_name not in all_tool_names:
                    messages.append(
                        {
                            "role": "user",
                            "content": f"工具 '{tool_name}' 不存在，请使用以下工具之一：{', '.join(all_tool_names)}",
                        }
                    )
                    continue

                result = _execute_tool_call(db, tool_name, arguments)

                if isinstance(result, dict) and "error" not in result:
                    all_tool_results.append({"tool": tool_name, "result": result})
                    tool_result_text = f"\n工具 {tool_name} 返回结果：\n{json.dumps(result, ensure_ascii=False, indent=2)}"

                    messages.append({"role": "assistant", "content": response_text})
                    messages.append({
                        "role": "user",
                        "content": f"工具执行结果如下：{tool_result_text}\n\n请基于以上工具返回的结果，综合回答用户的原始问题。如需更多信息可继续调用其他工具。",
                    })
                else:
                    messages.append({
                        "role": "assistant",
                        "content": response_text,
                    })
                    messages.append({
                        "role": "user",
                        "content": f"工具 '{tool_name}' 执行失败或返回错误：{json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)}\n\n请提供更具体的问题描述，或尝试调用其他可用工具。",
                    })

        except Exception as exc:
            logger.error(f"Agent execution failed: {exc}")
            if not tool_results:
                fallback_text = f"\n工具调用汇总：\n"
                for tr in tool_results:
                    fallback_text += f"\n\n{tr.get('tool', '')}: {json.dumps(tr.get('result', ''), ensure_ascii=False)}"
                fallback_text += "\n\n基于以上工具返回的数据，请分析并回答用户的原始问题。"
                messages.append({"role": "user", "content": fallback_text})

                try:
                    import ollama

                    client = ollama.Client(host=OLLAMA_BASE_URL)
                    response = client.chat(
                        model=OLLAMA_MODEL,
                        messages=messages,
                    )
                    response_text = response.get("message", {}).get("content", "")
                    return response_text, []
                except Exception as e:
                    logger.error(f"Fallback RAG also failed: {e}")
                    return "抱歉，智能体工具调用失败，请稍后重试。", []

    references = []
    for doc in docs:
        source = doc.get("metadata", {}).get("source_file", "")
        if source and source not in references:
            references.append(source)
    for tr in tool_results:
        ref = f"业务数据查询: {tr.get('tool', '')}"
        if ref not in references:
            references.append(ref)
    return "抱歉，智能体未能完成分析。", references
