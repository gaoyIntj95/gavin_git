from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

try:
    from neo4j import GraphDatabase
except Exception:  # pragma: no cover - optional dependency guard
    GraphDatabase = None  # type: ignore[assignment]


@dataclass(frozen=True)
class GraphNode:
    label: str
    name: str
    props: dict[str, Any] | None = None


@dataclass(frozen=True)
class GraphEdge:
    source_label: str
    source_name: str
    relation: str
    target_label: str
    target_name: str
    props: dict[str, Any] | None = None


ALLOWED_NODE_LABELS = {
    "Standard",
    "Term",
    "Industry",
    "Market",
    "Policy",
    "Enterprise",
    "Park",
    "EmissionSource",
}
ALLOWED_RELATIONS = {
    "RELATED_TO",
    "AFFECTS",
    "BELONGS_TO",
    "USES_STANDARD",
    "HAS_CHILD",
    "APPLIES_TO",
    "PUBLISHED_BY",
    "INCLUDES",
    "CITES",
    "BENCHMARKS",
    "GOVERNS",
    "ASSOCIATED_WITH",
    "BASED_ON",
}
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class GraphService:
    def __init__(self) -> None:
        self.enabled = os.getenv("KG_ENABLED", "false").strip().lower() == "true"
        self.uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687").strip()
        self.user = os.getenv("NEO4J_USER", "neo4j").strip()
        self.password = os.getenv("NEO4J_PASSWORD", "neo4j").strip()
        self.database = os.getenv("NEO4J_DATABASE", "neo4j").strip()
        self._driver = None
        self._schema_ready = False
        self._connectivity_checked = False

    def is_ready(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, "knowledge_graph_disabled"
        if GraphDatabase is None:
            return False, "neo4j_driver_not_installed"
        if not self.uri or not self.user or not self.password:
            return False, "neo4j_config_incomplete"
        return True, "ok"

    def _get_driver(self):
        if self._driver is None:
            ok, reason = self.is_ready()
            if not ok:
                raise RuntimeError(reason)
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:
                pass
            self._driver = None
        self._schema_ready = False

    def run_cypher(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        driver = self._get_driver()
        with driver.session(database=self.database) as session:
            result = session.run(cypher, params or {})
            return [dict(rec) for rec in result]

    def _normalize_identifier(self, name: str, allowed: set[str], field_name: str) -> str:
        value = (name or "").strip()
        if value not in allowed:
            raise ValueError(f"invalid_{field_name}: {value}")
        if not _IDENTIFIER_PATTERN.match(value):
            raise ValueError(f"unsafe_{field_name}: {value}")
        return value

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        for label in ALLOWED_NODE_LABELS:
            cypher = f"CREATE INDEX kg_{label.lower()}_name IF NOT EXISTS FOR (n:{label}) ON (n.name)"
            self.run_cypher(cypher)
        self._schema_ready = True

    def check_connectivity(self) -> tuple[bool, str]:
        ok, reason = self.is_ready()
        if not ok:
            return False, reason
        try:
            self.run_cypher("RETURN 1 AS ok")
            self._connectivity_checked = True
            return True, "ok"
        except Exception as exc:
            return False, f"neo4j_connect_failed: {exc}"

    def merge_node(self, node: GraphNode) -> None:
        label = self._normalize_identifier(node.label, ALLOWED_NODE_LABELS, "label")
        self._ensure_schema()
        cypher = (
            f"MERGE (n:{label} {{name: $name}}) "
            "SET n += $props, n.updated_at = datetime() "
            "RETURN n"
        )
        self.run_cypher(cypher, {"name": node.name, "props": node.props or {}})

    def merge_edge(self, edge: GraphEdge) -> None:
        source_label = self._normalize_identifier(edge.source_label, ALLOWED_NODE_LABELS, "source_label")
        target_label = self._normalize_identifier(edge.target_label, ALLOWED_NODE_LABELS, "target_label")
        relation = self._normalize_identifier(edge.relation, ALLOWED_RELATIONS, "relation")
        self._ensure_schema()
        cypher = (
            f"MERGE (s:{source_label} {{name: $s_name}}) "
            f"MERGE (t:{target_label} {{name: $t_name}}) "
            f"MERGE (s)-[r:{relation}]->(t) "
            "SET r += $props, r.updated_at = datetime() "
            "RETURN s, r, t"
        )
        self.run_cypher(
            cypher,
            {
                "s_name": edge.source_name,
                "t_name": edge.target_name,
                "props": edge.props or {},
            },
        )

    def upsert_triples(self, edges: list[GraphEdge]) -> int:
        count = 0
        for edge in edges:
            self.merge_edge(edge)
            count += 1
        return count

    def query_relations(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        kw = (keyword or "").strip()
        if not kw:
            return []
        lim = max(1, min(int(limit), 30))

        exact_cypher = """
        MATCH (a)-[r]->(b)
        WHERE toLower(a.name) = toLower($kw) OR toLower(b.name) = toLower($kw)
        RETURN labels(a) AS a_labels, a.name AS a_name, type(r) AS relation,
               labels(b) AS b_labels, b.name AS b_name, properties(r) AS rel_props
        LIMIT $limit
        """
        rows = self.run_cypher(exact_cypher, {"kw": kw, "limit": lim})
        if rows:
            return rows

        fuzzy_cypher = """
        MATCH (a)-[r]->(b)
        WHERE toLower(a.name) CONTAINS toLower($kw) OR toLower(b.name) CONTAINS toLower($kw)
        RETURN labels(a) AS a_labels, a.name AS a_name, type(r) AS relation,
               labels(b) AS b_labels, b.name AS b_name, properties(r) AS rel_props
        LIMIT $limit
        """
        return self.run_cypher(fuzzy_cypher, {"kw": kw, "limit": lim})

    def query_policy_hierarchy(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        kw = (keyword or "").strip()
        if not kw:
            return []
        lim = max(1, min(int(limit), 30))

        exact_cypher = """
        MATCH (a:Policy)-[r]->(b:Policy)
        WHERE toLower(a.name) = toLower($kw) OR toLower(b.name) = toLower($kw)
        RETURN a.name AS parent_policy, type(r) AS relation, b.name AS child_policy, properties(r) AS rel_props
        LIMIT $limit
        """
        rows = self.run_cypher(exact_cypher, {"kw": kw, "limit": lim})
        if rows:
            return rows

        fuzzy_cypher = """
        MATCH (a:Policy)-[r]->(b:Policy)
        WHERE toLower(a.name) CONTAINS toLower($kw) OR toLower(b.name) CONTAINS toLower($kw)
        RETURN a.name AS parent_policy, type(r) AS relation, b.name AS child_policy, properties(r) AS rel_props
        LIMIT $limit
        """
        return self.run_cypher(fuzzy_cypher, {"kw": kw, "limit": lim})


_GRAPH_SERVICE = GraphService()

KG_TERMS = [
    "CBAM",
    "CCER",
    "碳足迹",
    "碳达峰",
    "碳中和",
    "ISO 14064",
    "GHG Protocol",
    "Scope 1",
    "Scope 2",
    "Scope 3",
    "碳市场",
]

_POLICY_HINT_TERMS = ["上级", "下级", "层级", "政策链", "政策体系"]


def _extract_term(question: str) -> str:
    q = (question or "").strip()
    if not q:
        return ""
    lower_q = q.lower()
    for t in KG_TERMS:
        if t.lower() in lower_q:
            return t
    m = re.search(r"[A-Za-z][A-Za-z0-9\-\s]{2,30}", q)
    if m:
        return m.group(0).strip()
    return q[:30]


def query_knowledge_graph(question: str, entity: str | None = None, top_k: int = 8) -> dict[str, Any]:
    ok, reason = _GRAPH_SERVICE.is_ready()
    if not ok:
        msg_map = {
            "knowledge_graph_disabled": "知识图谱未启用（KG_ENABLED=false），已跳过图谱查询。",
            "neo4j_driver_not_installed": "未安装 Neo4j 驱动（neo4j），请先安装依赖。",
            "neo4j_config_incomplete": "Neo4j 配置不完整，请检查 NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD。",
        }
        return {
            "ok": False,
            "error": reason,
            "message": msg_map.get(reason, "知识图谱服务不可用，已跳过图谱查询。"),
            "items": [],
        }

    try:
        if not _GRAPH_SERVICE._connectivity_checked:
            conn_ok, conn_reason = _GRAPH_SERVICE.check_connectivity()
            if not conn_ok:
                return {
                    "ok": False,
                    "error": conn_reason,
                    "message": "知识图谱连接失败，请检查 Neo4j 配置与服务状态。",
                    "items": [],
                }
        keyword = (entity or "").strip() or _extract_term(question)
        q = (question or "").lower()
        if any(k in q for k in _POLICY_HINT_TERMS):
            rows = _GRAPH_SERVICE.query_policy_hierarchy(keyword, limit=top_k)
            mode = "policy_hierarchy"
        else:
            rows = _GRAPH_SERVICE.query_relations(keyword, limit=top_k)
            mode = "entity_relation"
        return {
            "ok": True,
            "mode": mode,
            "keyword": keyword,
            "count": len(rows),
            "items": rows,
            "message": "ok" if rows else "no_graph_hit",
        }
    except Exception as exc:
        logger.warning("knowledge graph query failed: %s", exc)
        return {
            "ok": False,
            "error": str(exc),
            "message": "知识图谱查询失败",
            "items": [],
        }


def seed_minimal_kg() -> dict[str, Any]:
    ok, reason = _GRAPH_SERVICE.is_ready()
    if not ok:
        return {"ok": False, "error": reason, "count": 0}
    edges = [
        GraphEdge("Standard", "ISO 14064", "RELATED_TO", "Standard", "GHG Protocol", {"type": "核算标准"}),
        GraphEdge("Term", "CBAM", "AFFECTS", "Industry", "钢铁", {"scope": "出口贸易"}),
        GraphEdge("Term", "CCER", "BELONGS_TO", "Market", "碳市场", {"scope": "自愿减排"}),
        GraphEdge("Term", "碳足迹", "USES_STANDARD", "Standard", "ISO 14064", {"scope": "核算方法"}),
        GraphEdge("Policy", "国家双碳政策", "HAS_CHILD", "Policy", "省级双碳政策", {"level": "national->provincial"}),
        GraphEdge("Policy", "省级双碳政策", "HAS_CHILD", "Policy", "行业配套政策", {"level": "provincial->industry"}),
    ]
    count = _GRAPH_SERVICE.upsert_triples(edges)
    return {"ok": True, "count": count}


def upsert_knowledge_edges(edges: list[GraphEdge]) -> dict[str, Any]:
    ok, reason = _GRAPH_SERVICE.is_ready()
    if not ok:
        return {"ok": False, "error": reason, "count": 0}
    conn_ok, conn_reason = _GRAPH_SERVICE.check_connectivity()
    if not conn_ok:
        return {"ok": False, "error": conn_reason, "count": 0}
    count = _GRAPH_SERVICE.upsert_triples(edges)
    return {"ok": True, "count": count}
