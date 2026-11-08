# MinIO + Milvus + MySQL 联动说明

## 目标架构
- 原始文件：MinIO
- 文件元数据：MySQL（`knowledge_documents`）
- 向量索引：Milvus

## 一键启动基础设施
在项目根目录执行：

```powershell
docker compose -f docker-compose.infra.yml up -d
```

可视化入口：
- MinIO Console: `http://127.0.0.1:9001`
  - 用户名：`minioadmin`
  - 密码：`minioadmin`
- Attu(Milvus UI): `http://127.0.0.1:8001`

## 后端环境变量（已在 `carbon_ai/.env`）
- `DB_BACKEND=mysql`
- `MYSQL_*` 连接参数
- `MINIO_*` 连接参数
- `MILVUS_*` 连接参数
- `EMBEDDING_DIM=768`

## 启动后端
```powershell
cd D:\Carbon_AI_Project\carbon_ai\app
python main.py
```

## 健康检查
```text
GET /api/chat/health/dependencies
```

应看到：
- `minio.ok = true`
- `milvus.ok = true`

## 迁移历史知识库（可选）
如果你之前已有本地文件路径的知识库记录，执行：

```powershell
python D:\Carbon_AI_Project\carbon_ai\scripts\migrate_knowledge_to_minio_milvus.py
```

脚本会做三件事：
1. 把旧文件上传到 MinIO；
2. 更新 MySQL 里的 `file_url/object_key/file_size/storage_provider`；
3. 重新写入 Milvus 向量。

