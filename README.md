# Carbon AI 前后端项目

统一仓库：后端位于 `backend/`，Vue 前端位于 `frontend/`。

## 环境准备

- 建议 Python 3.11（部分锁定依赖不支持 Python 3.13）。
- Node.js 22.12+ 或 24，pnpm，Docker Desktop（用于 MySQL 等基础服务）。
- 如需本地 AI 功能，另行安装 Ollama 并下载所配置的对话、嵌入模型。

## 1. 配置与数据库

在仓库根目录打开 PowerShell：

```powershell
cd backend
Copy-Item .env.example .env
notepad .env
```

将所有 `change-me` 替换为自己的值。`MYSQL_ROOT_PASSWORD` 与 `MYSQL_PASSWORD` 应保持一致；JWT_SECRET_KEY 使用足够长的随机字符串。不要提交 `.env`。

```powershell
docker compose --env-file .env -f docker-compose.infra.yml up -d
```

基础服务包括 MySQL、MinIO、Milvus、Neo4j 和 Attu。数据库首次启动需等待就绪；已存在 Docker 数据卷时，修改环境变量不会更改原数据库密码。

## 2. 启动后端

接着在 `backend` 目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd carbon_ai
..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8017 --reload
```

API 文档：http://127.0.0.1:8017/docs ，健康检查：http://127.0.0.1:8017/health 。
数据库表由后端启动逻辑创建。上传、日志、报告等默认写入 `backend/runtime/`。

## 3. 启动前端

另开终端，在仓库根目录执行：

```powershell
cd frontend
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

访问 http://localhost:5173 。开发服务器将 `/api` 请求转发到后端 8017 端口。
构建命令：`corepack pnpm build`。如电脑未提供 corepack，请先安装 pnpm。

## 数据与分享

本仓库提供源码、依赖清单、配置示例和原项目文档；没有包含原电脑的数据库、上传文件、知识库、生成报告、向量数据、虚拟环境、node_modules 或容器镜像。业务数据需要通过双方约定的方式另外迁移。高级 AI 功能需按实际部署配置模型与服务。

原项目会初始化演示账户（admin/admin123、demo/demo123），部署给其他人使用前请修改密码。
`backend/docs/` 和 `backend/README.md` 是原始开发资料，其中部分旧路径、SQLite 和启动命令已过时，以本文件为准。

## 本次整理与验证

- 保留前后端源码，原 D 盘目录未修改。
- 移除分享副本中的硬编码 JWT 密钥与 MySQL 密码，改用本地环境配置。
- 修正后端 Dockerfile 的入口及端口。
- 已执行 Python 语法检查和分享文件检查。未进行完整运行验收；需要新环境安装依赖并启动数据库、模型等外部服务后验证。
