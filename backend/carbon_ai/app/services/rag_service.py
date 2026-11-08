from __future__ import annotations

import logging
import os
import re
from datetime import datetime

from app.services.llm_gateway import (
    REMOTE_LLM_ENABLED,
    chat_messages,
    check_ollama_health,
    check_remote_llm_health,
)
from app.services.vector_store import add_documents, similarity_search_all

logger = logging.getLogger(__name__)

FALLBACK_ENABLED = True

KB_FALLBACK_GUIDANCE = (
    "当前知识库未找到高度相关的内容。建议：\n"
    "1. 上传更多专业文档到知识库后重试\n"
    "2. 尝试使用更具体的关键词提问\n"
    "3. 当前咨询范围包括：碳盘查、碳核算、碳市场、CBAM、ESG 等双碳领域"
)
RAG_KB_MISS_PREFIX = "知识库暂无相关文档命中，以下回答基于通用知识，仅供参考。"
RAG_FALLBACK_REASON_NO_RELEVANT = "知识库无高相关命中（已自动切换通用回答）"
RAG_FALLBACK_REASON_LOW_COVERAGE = "知识库关键词覆盖不足（已自动切换通用回答）"
GENERAL_LLM_REFERENCE_NO_KB = "通用大模型回答（无知识库命中）"
GENERAL_LLM_REFERENCE_REMOTE_TIMEOUT_LOCAL = "通用大模型回答（远端超时后自动切换本地）"
GENERAL_LLM_REFERENCE_UNAVAILABLE = "通用大模型不可用（已输出依赖诊断）"
GENERAL_LLM_UNAVAILABLE_PREFIX = "当前通用大模型服务暂不可用。"
WEB_REFERENCE_NO_URL = "联网检索结果（无可用URL）"
WEB_SYNTHESIS_UNAVAILABLE_PREFIX = "联网检索已执行，但当前通用大模型服务不可用，无法完成综合生成。"

RAG_SYSTEM_PROMPT = """你是“智碳管家”AI 咨询助手，专注于双碳（碳达峰、碳中和）领域问答。

【角色与边界】
- 你必须优先依据“参考文档”作答，尤其是核算、边界、标准、条款、因子、公式、文号、阈值、口径等硬核专业内容。
- 对硬核专业内容：仅允许使用参考文档信息，禁止使用模型记忆补全、禁止猜测、禁止编造。
- 对基础科普内容（如概念解释、常识性背景）：可使用通用知识，但必须明确标注“此部分基于通用知识，仅供参考”。

【证据要求】
- 结论必须可追溯；凡使用参考文档，必须给出：文档来源、章节、页码。
- 若参考文档证据不足、冲突或缺失，必须明确说明“不足以支持结论”，并指出缺失点；不得延伸推断。

【输出纪律】
- 统一使用中文。
- 不编造政策、标准编号、条款、数据、案例。
- 若用户问题超出材料范围，先说明边界，再给出可执行的补充建议（如需补充哪些文档/参数）。"""

RAG_QA_TEMPLATE = """参考文档：
{context}

---

用户问题：{question}

请严格按以下规则回答：

1) 先判定问题类型
- A. 硬核专业：核算、边界、标准、条款、因子、公式、口径、文号、数值
- B. 基础科普：概念性解释、非条款性背景说明

2) 作答约束
- A类：只能使用“参考文档”内容，禁止调用通用知识补全。
- B类：可补充通用知识，但必须单独标注“此部分基于通用知识，仅供参考”。
- 若证据不足：必须明确写“当前参考文档不足以支持该结论”，并列出缺失信息；禁止编造。

3) 输出格式（必须严格一致）
【回答】
- 给出简明、可执行结论；仅陈述有证据支持的内容。

【依据】
- 文档来源：...
- 章节：...
- 页码：...
- 证据摘录：...（简短原文要点）

【不确定性与边界】
- 若存在证据不足/冲突，明确说明不确定点与原因。

【通用知识补充】（仅当B类且确有必要时出现）
- 此部分基于通用知识，仅供参考：..."""

GENERAL_SYSTEM_PROMPT = """你是“智碳管家”AI 咨询助手。

你当前在“通用知识回答”模式下，必须遵守：
1. 仅回答基础科普、通用方法论、非具体条款类问题。
2. 不能给出任何未经文档支撑的具体标准条文、文号、精确阈值、精确因子或合规结论。
3. 若用户请求硬核专业判断（核算/边界/标准/条款/因子/公式），必须明确提示：需结合知识库文档核验后才能给出结论。
4. 回答中必须包含固定提示：“此回答基于通用知识，仅供参考”。
5. 使用中文，结构清晰，避免绝对化表述。"""

WEB_QA_TEMPLATE = """以下是联网检索结果（可能包含噪声）：
{web_context}

---

用户问题：{question}

请按以下规则回答：
1. 优先基于检索结果作答，不得把未出现在检索结果中的具体事实当作已证实结论。
2. 涉及标准、条款、文号、数据、时间点时，必须标注来源编号（如[网页1]），并尽量对应到具体表述。
3. 若检索证据不足或相互冲突，必须明确说明“不确定，现有检索结果不足以支持结论”。
4. 禁止编造来源、编造条文、编造数值。
5. 输出格式统一为：

【回答】
...

【来源依据】
- [网页X] 证据要点：...
- [网页Y] 证据要点：...

【不确定性与边界】
...

若需要，再补充：
【通用知识补充】
- 此部分基于通用知识，仅供参考：..."""

PRESET_RULES = [
    {
        "keywords": ["组织边界", "边界方法"],
        "answer": "组织边界的界定支持三种方法：运营控制法、控股法和财务控制法。ISO 14064-1 推荐使用运营控制法，即对运营具有完整决策权的设施均应纳入组织边界。在项目建档时应固化边界方法选择。",
        "reference": "ISO 14064-1 / GHG Protocol",
    },
    {
        "keywords": ["scope1", "scope 1", "范围一", "直接排放"],
        "answer": "Scope 1（范围一）是直接温室气体排放，即组织拥有或控制的排放源产生的排放。主要包括：固定燃烧（如锅炉、发电机）、移动燃烧（如车辆）、工艺排放（如化学反应）、无组织排放（如冷媒泄漏）等。在 ISO 14064-1 中归类为第 1 类排放。",
        "reference": "ISO 14064-1 第 5.2 条",
    },
    {
        "keywords": ["scope2", "scope 2", "范围二", "间接排放"],
        "answer": "Scope 2（范围二）是外购电力、热力或蒸汽产生的间接温室气体排放。核算方法有位置法和市场法两种：位置法使用电网平均排放因子，市场法考虑合同工具（如绿证）。当前系统默认采用位置法核算。",
        "reference": "ISO 14064-1 / GHG Protocol Scope 2 Guidance",
    },
    {
        "keywords": ["scope3", "scope 3", "范围三"],
        "answer": "Scope 3（范围三）是其他间接温室气体排放，包括上下游排放，如员工通勤、商务差旅、外购商品和服务、废弃物处理等。ISO 14064-1 将其归为第 3 类排放，目前系统支持录入但暂不强制核算。",
        "reference": "GHG Protocol Corporate Value Chain Standard",
    },
    {
        "keywords": ["iso14064", "iso 14064"],
        "answer": "ISO 14064-1 是国际标准化组织发布的温室气体量化与报告标准，最新常用版本为 2018 版。它将排放分为三大类：第 1 类（直接排放 / Scope 1）、第 2 类（间接能源排放 / Scope 2）、第 3 类（其他间接排放 / Scope 3）。该标准要求进行不确定性评估和证据管理。",
        "reference": "ISO 14064-1:2018",
    },
    {
        "keywords": ["js/t 303", "js/t303", "公共机构", "303-2026"],
        "answer": "JS/T 303—2026 是中国公共机构温室气体排放核算指南，专门针对公共机构（如政府机关、学校、医院等）。与 ISO 14064 的主要区别包括：(1) 排放只分直接排放和间接排放两大类；(2) 间接排放进一步细分为电力和热力；(3) 支持转供量扣减；(4) 内置 4 类标准排放源（外购电力、汽油、柴油、外购热力）。",
        "reference": "JS/T 303—2026",
    },
    {
        "keywords": ["cbam", "碳边境", "碳关税"],
        "answer": "CBAM（碳边境调节机制）是欧盟自 2023 年 10 月起实施的碳关税制度，覆盖水泥、钢铁、铝、化肥、电力、氢能等行业。申报需要提供：产品碳足迹数据、排放源数据、生产过程记录和官方申报模板。企业需计算出口产品的碳足迹（总排放 ÷ 产品数量），并预估应缴碳关税。",
        "reference": "EU CBAM Regulation 2023/956",
    },
    {
        "keywords": ["履约", "配额", "碳市场"],
        "answer": "碳市场履约是指重点排放单位在规定期限内上缴与排放量等量的碳配额。配额分配方式通常包括祖父法、基准法和混合法。履约成本优化时，可关注 CCER 抵消和绿电抵扣等政策工具，并优先采用成本更低的履约方案。",
        "reference": "全国碳市场交易管理办法",
    },
    {
        "keywords": ["排放因子", "因子"],
        "answer": "排放因子是核算温室气体排放的关键参数，表示单位活动数据对应的排放量。因子来源优先级通常为：国际排放因子、国家排放因子、区域排放因子、省级排放因子。系统支持因子自动匹配和手动输入两种方式。",
        "reference": "JS/T 303—2026 表 A.1 / 表 A.2",
    },
    {
        "keywords": ["不确定性", "数据质量"],
        "answer": "不确定性评估是 ISO 14064-1 的核心要求。常见评价方式中，活动数据类别可区分为自动连续监测、定期量测/抄表/铭牌、自行推估；排放因子类别可区分为国际、国家、区域等来源。系统可基于评分与排放占比计算加权结果，用于识别高风险数据点。",
        "reference": "ISO 14064-1:2018 第 7 章",
    },
]

# Chroma cosine distance: lower is better (0 is best).
# If top docs are all above this distance, treat as "no reliable KB hit".
RAG_MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "0.35"))
RAG_CONTEXT_MAX_CHARS = int(os.getenv("RAG_CONTEXT_MAX_CHARS", "4200"))
RAG_RECALL_CANDIDATES = int(os.getenv("RAG_RECALL_CANDIDATES", "24"))
RAG_RERANK_TOPK = int(os.getenv("RAG_RERANK_TOPK", "6"))
RAG_ENABLE_MULTI_RECALL = os.getenv("RAG_ENABLE_MULTI_RECALL", "true").lower() == "true"
RAG_DIAGNOSTIC_LOG = os.getenv("RAG_DIAGNOSTIC_LOG", "true").lower() == "true"
RAG_PARENT_CONTEXT_EXPAND = os.getenv("RAG_PARENT_CONTEXT_EXPAND", "true").lower() == "true"
RAG_PARENT_CONTEXT_TOPN = int(os.getenv("RAG_PARENT_CONTEXT_TOPN", "6"))
RAG_STRUCTURED_RECALL_BONUS = float(os.getenv("RAG_STRUCTURED_RECALL_BONUS", "0.06"))

DOMAIN_KEYWORDS = [
    "碳足迹",
    "产品碳足迹",
    "生命周期",
    "lca",
    "电池",
    "组件",
    "边界",
    "组织边界",
    "核算",
    "排放因子",
    "cbam",
    "scope",
    "iso 14064",
    "iso14064",
    "iso 14067",
    "iso14067",
    "温室气体",
    "ghg",
    "碳中和",
    "碳达峰",
    "双碳",
    "碳市场",
    "配额",
    "履约",
    "绿电",
    "碳核查",
    "碳盘查",
]

TRUST_SOURCE_KEYWORDS = [
    "iso",
    "ghg protocol",
    "ipcc",
    "js/t",
    "生态环境部",
    "国家发展改革委",
    "欧盟",
    "cbam",
]

QUERY_EXPANSIONS = {
    "scope1": ["范围一", "直接排放", "第1类排放"],
    "scope2": ["范围二", "间接能源排放", "外购电力", "外购热力"],
    "scope3": ["范围三", "其他间接排放", "价值链"],
    "iso14064": ["iso 14064", "温室气体核算", "组织层级核算"],
    "iso 14064": ["iso14064", "温室气体核算", "组织层级核算"],
    "cbam": ["碳边境调节机制", "欧盟碳关税", "碳边境"],
    "js/t303": ["js/t 303", "公共机构温室气体", "公共机构核算"],
    "js/t 303": ["js/t303", "公共机构温室气体", "公共机构核算"],
    "排放因子": ["因子来源", "活动数据", "核算参数"],
    "碳市场": ["配额", "履约", "ccer"],
}


def _call_ollama_chat(
    prompt: str,
    system_prompt: str = RAG_SYSTEM_PROMPT,
    history_messages: list[dict[str, str]] | None = None,
    allow_rule_fallback: bool = True,
    task: str = "rag",
) -> str:
    try:
        messages = [{"role": "system", "content": system_prompt}]

        if history_messages:
            messages.extend(history_messages[-10:])

        messages.append({"role": "user", "content": prompt})
        return chat_messages(messages=messages, task=task, contains_sensitive=False)
    except Exception as exc:
        logger.error("Ollama chat call failed: %s", exc)
        if FALLBACK_ENABLED and allow_rule_fallback:
            return _fallback_answer(prompt)
        raise


def _fallback_answer(question: str) -> str:
    match = ask_with_preset_rules(question)
    if match is None:
        return KB_FALLBACK_GUIDANCE
    answer, _ = match
    return answer


def ask_with_preset_rules(question: str) -> tuple[str, list[str]] | None:
    lower_q = question.lower()
    hits = []
    for rule in PRESET_RULES:
        if any(kw in lower_q for kw in rule["keywords"]):
            hits.append(rule)
    if not hits:
        return None
    answer_parts = [f"- {hit['answer']}\n  来源：{hit['reference']}" for hit in hits[:3]]
    references = []
    for hit in hits[:3]:
        ref = hit.get("reference", "")
        if ref and ref not in references:
            references.append(ref)
    return "\n".join(answer_parts), references


def _tokenize_text(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not cleaned:
        return []
    try:
        import jieba  # type: ignore

        tokens = [tok.strip() for tok in jieba.cut(cleaned) if tok and tok.strip()]
    except Exception:
        tokens = re.findall(r"[\u4e00-\u9fff]{1,}|[a-z0-9\-/\.]+", cleaned)
    return [t for t in tokens if len(t) >= 2]


def _expand_queries(question: str) -> list[str]:
    base = (question or "").strip()
    if not base:
        return []
    lower_q = base.lower()
    queries = [base]
    for key, aliases in QUERY_EXPANSIONS.items():
        if key in lower_q:
            queries.append(f"{base} {' '.join(aliases[:2])}")
            queries.extend(aliases[:2])
    # Add domain keyword hints for sparse queries
    if len(_tokenize_text(base)) <= 3:
        q_keywords = _question_keywords(base)[:3]
        if q_keywords:
            queries.append(f"{base} {' '.join(q_keywords)}")
    dedup = []
    seen = set()
    for q in queries:
        qn = q.strip()
        if qn and qn not in seen:
            seen.add(qn)
            dedup.append(qn)
    return dedup[:4]


def _doc_key(doc: dict) -> str:
    metadata = doc.get("metadata") or {}
    parent_id = str(metadata.get("parent_chunk_id", "")).strip()
    source = str(metadata.get("source_file", "")).strip()
    if source and parent_id:
        return f"{source}::parent::{parent_id}"
    content = (doc.get("content") or "").strip()
    head = content[:180]
    return f"{source}::{head}"


def _unique_docs(docs: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen = set()
    for doc in docs:
        key = _doc_key(doc)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(doc)
    return result


def _lexical_overlap_score(question: str, text: str) -> float:
    q_tokens = set(_tokenize_text(question))
    if not q_tokens:
        return 0.0
    d_tokens = set(_tokenize_text(text))
    if not d_tokens:
        return 0.0
    overlap = q_tokens.intersection(d_tokens)
    return len(overlap) / max(len(q_tokens), 1)


def _source_trust_bonus(doc: dict) -> float:
    source = str((doc.get("metadata") or {}).get("source_file", "")).lower()
    if not source:
        return 0.0
    return 0.03 if any(kw in source for kw in TRUST_SOURCE_KEYWORDS) else 0.0


def _keyword_coverage_bonus(question: str, text: str) -> float:
    kws = _question_keywords(question)
    if not kws:
        return 0.0
    lower_text = (text or "").lower()
    hit = sum(1 for kw in kws if kw in lower_text)
    return 0.07 * (hit / max(len(kws), 1))


def _semantic_relevance(doc: dict) -> float:
    distance = doc.get("distance")
    if distance is None:
        return 0.4
    try:
        d = float(distance)
    except Exception:
        return 0.4
    # cosine distance: lower is better
    return max(0.0, min(1.0, 1.0 - d))


def _structured_chunk_bonus(question: str, doc: dict) -> float:
    metadata = doc.get("metadata") or {}
    if not isinstance(metadata, dict):
        return 0.0

    bonus = 0.0
    doc_type = str(metadata.get("doc_type", "")).lower()
    if doc_type in {"policy", "standard"}:
        bonus += RAG_STRUCTURED_RECALL_BONUS * 0.6
    elif doc_type == "table":
        bonus += RAG_STRUCTURED_RECALL_BONUS * 0.45

    lower_q = (question or "").lower()
    content = (doc.get("content") or "").lower()

    if any(token in lower_q for token in ["scope", "iso", "js/t", "article", "clause", "section", "standard"]):
        if re.search(r"article\s*\d+|section\s*\d+|\d+(\.\d+){1,4}", content):
            bonus += RAG_STRUCTURED_RECALL_BONUS * 0.45

    if any(token in lower_q for token in ["factor", "coefficient", "value", "table", "ratio", "%"]):
        if doc_type == "table" or ("|" in content and "\n" in content):
            bonus += RAG_STRUCTURED_RECALL_BONUS * 0.45

    if len((doc.get("content") or "").strip()) < 60:
        bonus -= RAG_STRUCTURED_RECALL_BONUS * 0.35

    return max(-0.05, min(0.12, bonus))


def _rerank_docs(question: str, docs: list[dict], top_k: int) -> list[dict]:
    scored: list[tuple[float, dict]] = []
    for doc in docs:
        text = (doc.get("content") or "")
        score = (
            0.67 * _semantic_relevance(doc)
            + 0.20 * _lexical_overlap_score(question, text)
            + _keyword_coverage_bonus(question, text)
            + _source_trust_bonus(doc)
            + _structured_chunk_bonus(question, doc)
        )
        enriched = dict(doc)
        enriched["rerank_score"] = round(score, 6)
        scored.append((score, enriched))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[: max(1, top_k)]]


def _multi_recall(question: str, k: int) -> tuple[list[dict], dict]:
    queries = _expand_queries(question)
    if not queries:
        return [], {"queries": [], "per_query_hits": {}, "candidate_count": 0, "dedup_count": 0}
    candidates: list[dict] = []
    each_k = max(k, RAG_RECALL_CANDIDATES // max(len(queries), 1))
    per_query_hits: dict[str, int] = {}

    # Route-1: vector retrieval (primary route).
    vector_docs = similarity_search_all(question, k=each_k)
    per_query_hits[question] = len(vector_docs)

    # Build candidate pool for BM25 from expanded vector recalls.
    for q in queries:
        hits = similarity_search_all(q, k=each_k)
        per_query_hits[q] = len(hits)
        candidates.extend(hits)
    candidates.extend(vector_docs)
    bm25_pool = _unique_docs(candidates)

    # Route-2: BM25 lexical retrieval (pure Python + jieba).
    bm25_docs: list[dict] = []
    if bm25_pool:
        try:
            import math
            import jieba  # type: ignore

            query_tokens = [tok.strip() for tok in jieba.cut((question or "").lower()) if tok and tok.strip()]
            query_tokens = [tok for tok in query_tokens if len(tok) >= 2]
            if query_tokens:
                tokenized_docs: list[list[str]] = []
                doc_freq: dict[str, int] = {}
                doc_lens: list[int] = []

                for doc in bm25_pool:
                    content = (doc.get("content") or "").lower()
                    tokens = [tok.strip() for tok in jieba.cut(content) if tok and tok.strip()]
                    tokens = [tok for tok in tokens if len(tok) >= 2]
                    tokenized_docs.append(tokens)
                    doc_lens.append(len(tokens))
                    for token in set(tokens):
                        doc_freq[token] = doc_freq.get(token, 0) + 1

                n_docs = len(tokenized_docs)
                avgdl = (sum(doc_lens) / n_docs) if n_docs else 0.0
                k1 = 1.5
                b = 0.75

                scored_docs: list[tuple[float, dict]] = []
                for idx, doc in enumerate(bm25_pool):
                    tokens = tokenized_docs[idx]
                    if not tokens:
                        continue
                    tf: dict[str, int] = {}
                    for token in tokens:
                        tf[token] = tf.get(token, 0) + 1

                    score = 0.0
                    dl = max(doc_lens[idx], 1)
                    for q_token in query_tokens:
                        f = tf.get(q_token, 0)
                        if f <= 0:
                            continue
                        df = doc_freq.get(q_token, 0)
                        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                        denom = f + k1 * (1 - b + b * dl / max(avgdl, 1.0))
                        score += idf * ((f * (k1 + 1)) / max(denom, 1e-9))

                    if score > 0:
                        scored_docs.append((score, doc))

                scored_docs.sort(key=lambda x: x[0], reverse=True)
                bm25_docs = [doc for _, doc in scored_docs[: max(k, RAG_RERANK_TOPK)]]
        except Exception as exc:
            logger.warning("BM25 route failed, continue with vector-only candidates: %s", exc)

    merged_docs = _unique_docs(vector_docs + bm25_docs)
    reranked = _rerank_docs(question, merged_docs, top_k=max(k, RAG_RERANK_TOPK))
    diagnostics = {
        "queries": queries,
        "per_query_hits": per_query_hits,
        "candidate_count": len(candidates),
        "dedup_count": len(merged_docs),
        "vector_count": len(vector_docs),
        "bm25_count": len(bm25_docs),
    }
    return reranked, diagnostics


def _summarize_docs_for_log(docs: list[dict], limit: int = 3) -> list[dict]:
    summary = []
    for doc in docs[: max(1, limit)]:
        source = str((doc.get("metadata") or {}).get("source_file", ""))
        distance = doc.get("distance")
        summary.append(
            {
                "source": source,
                "distance": round(float(distance), 4) if distance is not None else None,
                "rerank_score": doc.get("rerank_score"),
                "preview": (doc.get("content") or "").strip().replace("\n", " ")[:80],
            }
        )
    return summary


def _log_rag_diagnostics(question: str, payload: dict) -> None:
    if not RAG_DIAGNOSTIC_LOG:
        return
    # Use info level for online observability; payload is intentionally compact.
    logger.info(
        "RAG_DIAG q='%s' mode=%s source_docs=%s relevant=%s keyword_ok=%s fallback=%s details=%s",
        (question or "").replace("\n", " ")[:120],
        payload.get("mode"),
        payload.get("source_docs"),
        payload.get("relevant_docs"),
        payload.get("keyword_ok"),
        payload.get("fallback_reason"),
        payload.get("details"),
    )


def retrieve_relevant_docs(question: str, k: int = 3) -> list[dict]:
    if not RAG_ENABLE_MULTI_RECALL:
        return similarity_search_all(question, k=k)
    try:
        docs, _ = _multi_recall(question, k=max(k, 3))
        if docs:
            return docs
    except Exception as exc:
        logger.warning("Multi-recall failed, fallback to single recall: %s", exc)
    return similarity_search_all(question, k=k)


def _sort_docs_by_origin(docs: list[dict]) -> list[dict]:
    def _int(value, default: int = 10**12) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _key(doc: dict) -> tuple:
        meta = doc.get("metadata") or {}
        source = str(meta.get("source_file", ""))
        parent_start = _int(meta.get("parent_start_offset"))
        child_start = _int(meta.get("start_offset"))
        parent_id = str(meta.get("parent_chunk_id", ""))
        return (source, parent_start, child_start, parent_id)

    return sorted(docs, key=_key)


def _expand_parent_context(docs: list[dict]) -> list[dict]:
    if not docs:
        return []

    if not RAG_PARENT_CONTEXT_EXPAND:
        return docs

    expanded: list[dict] = []
    seen = set()

    for doc in docs[: max(1, RAG_PARENT_CONTEXT_TOPN)]:
        meta = dict(doc.get("metadata") or {})
        parent_id = str(meta.get("parent_chunk_id", "")).strip()
        source = str(meta.get("source_file", "")).strip()
        parent_text = str(meta.get("parent_text", "") or "").strip()

        key = (source, parent_id or (doc.get("content") or "")[:120])
        if key in seen:
            continue
        seen.add(key)

        if parent_id and parent_text:
            merged = dict(doc)
            merged["content"] = parent_text
            merged_meta = dict(meta)
            merged_meta["chunk_role"] = "parent_expanded"
            merged["metadata"] = merged_meta
            expanded.append(merged)
        else:
            expanded.append(doc)

    for doc in docs[max(1, RAG_PARENT_CONTEXT_TOPN) :]:
        expanded.append(doc)

    return _sort_docs_by_origin(expanded)


def _build_context(docs: list[dict]) -> str:
    if not docs:
        return "(no matched docs)"

    ordered_docs = _expand_parent_context(docs)
    parts = []
    budget = RAG_CONTEXT_MAX_CHARS
    used = 0

    for i, doc in enumerate(ordered_docs, 1):
        metadata = doc.get("metadata") or {}
        source = metadata.get("source_file", "unknown")
        section = metadata.get("section") or "main"
        page = metadata.get("page")
        distance = doc.get("distance", 0)
        try:
            relevance = 1 - float(distance)
        except Exception:
            relevance = 0.0

        page_text = f" page:{page}" if page is not None else ""
        header = f"[Doc{i}] source:{source} section:{section}{page_text} relevance:{relevance:.2f}"
        content = (doc.get("content") or "").strip()
        remain = max(budget - used - len(header) - 2, 0)
        if remain <= 0:
            break
        if len(content) > remain:
            content = content[:remain] + "..."
        block = f"{header}\n{content}"
        parts.append(block)
        used += len(block)
        if used >= budget:
            break

    return "\n\n".join(parts)


def _build_references(docs: list[dict]) -> list[str]:
    references = []
    for doc in docs:
        source = doc.get("metadata", {}).get("source_file", "")
        if source and source not in references:
            references.append(source)
    return references


def _filter_relevant_docs(docs: list[dict], max_distance: float = RAG_MAX_DISTANCE) -> list[dict]:
    if not docs:
        return []
    filtered: list[dict] = []
    for doc in docs:
        distance = doc.get("distance")
        # If distance missing, keep doc to avoid dropping all context unexpectedly.
        if distance is None:
            filtered.append(doc)
            continue
        try:
            if float(distance) <= max_distance:
                filtered.append(doc)
        except Exception:
            filtered.append(doc)
    return filtered


def _question_keywords(question: str) -> list[str]:
    lower_q = (question or "").lower()
    return [kw for kw in DOMAIN_KEYWORDS if kw in lower_q]


def _has_keyword_coverage(question: str, docs: list[dict], min_coverage: float = 0.5) -> bool:
    q_keywords = _question_keywords(question)
    if not q_keywords:
        # No explicit domain keyword in question, skip lexical gate.
        return True
    joined_docs = " ".join((doc.get("content") or "").lower() for doc in docs if isinstance(doc, dict))
    if not joined_docs.strip():
        return False
    hit_count = sum(1 for kw in q_keywords if kw in joined_docs)
    return (hit_count / max(len(q_keywords), 1)) >= min_coverage


def ask_with_rag(
    question: str,
    session_id: str,
    k: int = 3,
    docs: list[dict] | None = None,
    history_messages: list[dict[str, str]] | None = None,
) -> tuple[str, list[str]]:
    diagnostics: dict = {
        "mode": "single",
        "details": {},
        "source_docs": 0,
        "relevant_docs": 0,
        "keyword_ok": None,
        "fallback_reason": None,
    }

    if docs is not None:
        working_docs = docs
        diagnostics["mode"] = "external_docs"
    elif RAG_ENABLE_MULTI_RECALL:
        try:
            working_docs, recall_diag = _multi_recall(question, k=max(k, 3))
            diagnostics["mode"] = "multi"
            diagnostics["details"] = recall_diag
        except Exception as exc:
            logger.warning("Multi-recall failed in ask_with_rag, fallback to single recall: %s", exc)
            working_docs = similarity_search_all(question, k=max(k, 3))
            diagnostics["mode"] = "single_fallback"
            diagnostics["details"] = {"error": str(exc)[:180]}
    else:
        working_docs = similarity_search_all(question, k=max(k, 3))

    diagnostics["source_docs"] = len(working_docs)
    working_docs = _unique_docs(working_docs)
    reranked_docs = _rerank_docs(question, working_docs, top_k=max(k, RAG_RERANK_TOPK))
    diagnostics["details"]["top_reranked"] = _summarize_docs_for_log(reranked_docs, limit=3)

    relevant_docs = _filter_relevant_docs(reranked_docs)
    diagnostics["relevant_docs"] = len(relevant_docs)
    keyword_ok = _has_keyword_coverage(question, relevant_docs)
    diagnostics["keyword_ok"] = keyword_ok

    if not relevant_docs or not keyword_ok:
        general_answer, _ = ask_with_general_llm(
            question=question,
            history_messages=history_messages,
        )
        answer = (
            f"{RAG_KB_MISS_PREFIX}\n\n"
            f"{general_answer}"
        )
        if not relevant_docs:
            reason = RAG_FALLBACK_REASON_NO_RELEVANT
        else:
            reason = RAG_FALLBACK_REASON_LOW_COVERAGE
        diagnostics["fallback_reason"] = reason
        _log_rag_diagnostics(question, diagnostics)
        return answer, [reason]

    context = _build_context(relevant_docs)
    prompt = RAG_QA_TEMPLATE.format(context=context, question=question)
    answer = _call_ollama_chat(prompt, history_messages=history_messages)
    references = _build_references(relevant_docs)
    _log_rag_diagnostics(question, diagnostics)
    return answer, references


def ask(
    question: str,
    session_id: str = "default",
    k: int = 3,
    history_messages: list[dict[str, str]] | None = None,
) -> tuple[str, list[str]]:
    return ask_with_rag(question, session_id, k=k, history_messages=history_messages)


def ask_with_general_llm(
    question: str,
    history_messages: list[dict[str, str]] | None = None,
) -> tuple[str, list[str]]:
    prompt = (
        "请基于通用双碳知识回答以下问题，并在结尾补充“此回答基于通用知识，仅供参考”。\n\n"
        f"用户问题：{question}"
    )
    try:
        answer = _call_ollama_chat(
            prompt,
            system_prompt=GENERAL_SYSTEM_PROMPT,
            history_messages=history_messages,
            allow_rule_fallback=False,
            task="general",
        )
        return answer, [GENERAL_LLM_REFERENCE_NO_KB]
    except Exception as exc:
        # Final guard: if remote path times out, force one local-only attempt.
        try:
            forced_local_answer = _call_ollama_chat(
                prompt,
                system_prompt=GENERAL_SYSTEM_PROMPT,
                history_messages=history_messages,
                allow_rule_fallback=False,
                task="agent",  # route to local by default (REMOTE_FOR_AGENT=false)
            )
            return forced_local_answer, [GENERAL_LLM_REFERENCE_REMOTE_TIMEOUT_LOCAL]
        except Exception:
            pass

        remote_ok, remote_msg = check_remote_llm_health()
        ollama_ok, ollama_msg = check_ollama_health()
        diagnose = []
        if REMOTE_LLM_ENABLED:
            diagnose.append(f"线上模型: {'可用' if remote_ok else '不可用'}（{remote_msg}）")
        diagnose.append(f"本地Ollama: {'可用' if ollama_ok else '不可用'}（{ollama_msg}）")
        diagnose_text = "；".join(diagnose)
        return (
            f"{GENERAL_LLM_UNAVAILABLE_PREFIX}"
            f"诊断结果：{diagnose_text}。"
            f"原始错误：{str(exc)[:200]}",
            [GENERAL_LLM_REFERENCE_UNAVAILABLE],
        )


def ask_with_web_context(
    question: str,
    web_results: list[dict],
    history_messages: list[dict[str, str]] | None = None,
) -> tuple[str, list[str]]:
    if not web_results:
        return ask_with_general_llm(question, history_messages=history_messages)

    lines = []
    refs = []
    for idx, item in enumerate(web_results, 1):
        title = item.get("title", "未知标题")
        snippet = item.get("snippet", "")
        url = item.get("url", "")
        lines.append(f"[网页{idx}] 标题: {title}\n摘要: {snippet}\n链接: {url}")
        if url and url not in refs:
            refs.append(url)

    prompt = WEB_QA_TEMPLATE.format(
        web_context="\n\n".join(lines),
        question=question,
    )
    try:
        answer = _call_ollama_chat(
            prompt,
            system_prompt=GENERAL_SYSTEM_PROMPT,
            history_messages=history_messages,
            allow_rule_fallback=False,
            task="web",
        )
        return answer, refs or [WEB_REFERENCE_NO_URL]
    except Exception as exc:
        return (
            f"{WEB_SYNTHESIS_UNAVAILABLE_PREFIX}"
            f"原始错误：{str(exc)[:200]}",
            refs or [WEB_REFERENCE_NO_URL],
        )


def index_document_chunks(
    chunks: list,
    source_file: str,
    extra_metadata: dict | None = None,
) -> int:
    if not chunks:
        return 0

    base = {"source_file": source_file, "indexed_at": datetime.utcnow().isoformat()}
    if isinstance(extra_metadata, dict):
        base.update(extra_metadata)

    normalized_chunks: list[str] = []
    metadatas: list[dict] = []

    for idx, chunk in enumerate(chunks):
        if isinstance(chunk, str):
            text = chunk.strip()
            if not text:
                continue
            normalized_chunks.append(text)
            meta = base.copy()
            meta.update(
                {
                    "chunk_index": idx,
                    "section": "main",
                    "page": None,
                    "start_offset": None,
                    "end_offset": None,
                    "doc_type": "general",
                    "toc_level": 0,
                    "parent_chunk_id": f"{source_file}:legacy:{idx}",
                    "chunk_role": "child",
                    "boundary_preserved": False,
                }
            )
            metadatas.append(meta)
            continue

        if isinstance(chunk, dict):
            text = str(chunk.get("text", "") or "").strip()
            if not text:
                continue
            normalized_chunks.append(text)
            chunk_meta = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            meta = base.copy()
            meta.update(chunk_meta)
            meta.setdefault("chunk_index", idx)
            meta.setdefault("section", "main")
            meta.setdefault("page", None)
            meta.setdefault("start_offset", None)
            meta.setdefault("end_offset", None)
            meta.setdefault("doc_type", "general")
            meta.setdefault("toc_level", 0)
            meta.setdefault("parent_chunk_id", f"{source_file}:parent:{idx}")
            meta.setdefault("chunk_role", "child")
            meta.setdefault("boundary_preserved", True)
            metadatas.append(meta)

    if not normalized_chunks:
        return 0

    return add_documents(normalized_chunks, metadatas=metadatas)


