# Carbon AI Project

基于你提供的三份文档（PRD/TDD/架构说明）搭建的 DEMO 版代码骨架，覆盖六大模块：

1. 智碳咨询助手（RAG 问答接口）
2. 智碳核算引擎（排放源管理、自动核算、合规校验）
3. 智碳报告生成（盘查/履约/CBAM 报告）
4. 碳市场履约助手（配额缺口、成本优化）
5. CBAM 申报助手（数据提取、模板导出）
6. 实用附加能力（批量导入、因子自动匹配、数据目录）

## 目录结构

```text
Carbon_AI_Project/
├── carbon_ai/
│   └── app/
│       ├── api/
│       ├── core/
│       ├── models/
│       ├── schemas/
│       ├── services/
│       └── utils/
├── frontend/
├── data/
├── tests/
└── requirements.txt
```

## 快速启动

```bash
pip install -r requirements.txt
cd carbon_ai
uvicorn app.main:app --reload
```

启动后访问：

- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 核心接口

- 项目管理：`/api/projects`
- 排放源管理：`/api/projects/{project_id}/emission-sources`
- 自动核算：`/api/projects/{project_id}/calculate`
- 合规校验：`/api/projects/{project_id}/validate`
- 智能问答：`/api/chat/ask`
- 报告生成：`/api/reports/inventory/{project_id}` 等
- 碳市场：`/api/carbon-market/quota-gap/{project_id}`、`/api/carbon-market/optimize/{project_id}`
- CBAM：`/api/cbam/extract/{project_id}`、`/api/cbam/template/{project_id}`

## 说明

- 数据库存储默认使用 SQLite（`carbon_ai/carbon_ai.db`）。
- 报告文件输出到 `data/reports/`。
- 上传文件暂存到 `data/uploads/`。

