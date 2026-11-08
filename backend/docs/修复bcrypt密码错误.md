# 修复 bcrypt 密码错误

## 问题

启动后端时出现以下错误：

```
ValueError: password cannot be longer than 72 bytes, truncate manually if necessary (e.g. my_password[:72])
```

## 原因

`bcrypt` 版本兼容性问题，在 Windows + Python 3.11 环境下出现 bug。

---

## 解决方案

### 方法 1：重置数据库（推荐）

**步骤 1：停止后端服务**
按 `Ctrl+C` 停止运行的 uvicorn 进程。

**步骤 2：运行重置脚本**

双击运行：`D:\Carbon_AI_Project\reset_db.bat`

或在 Anaconda Prompt 中运行：

```bash
cd D:\Carbon_AI_Project
del carbon_ai\carbon_ai.db
del carbon_ai.db
del data\chroma_db\chroma.sqlite3
```

**步骤 3：重新启动后端**

```bash
cd D:\Carbon_AI_Project\carbon_ai
conda activate py311
uvicorn app.main:app --host 127.0.0.1 --port 8017 --reload
```

---

### 方法 2：手动删除数据库文件

如果重置脚本不工作，手动删除以下文件：

1. `D:\Carbon_AI_Project\carbon_ai\carbon_ai.db`
2. `D:\Carbon_AI_Project\carbon_ai.db`
3. `D:\Carbon_AI_Project\data\chroma_db\chroma.sqlite3`

然后重新启动后端。

---

## 已修复的内容

| 文件                   | 修改内容                            |
| ---------------------- | ----------------------------------- |
| `app/core/security.py` | 改用 pbkdf2 密码哈希（移除 bcrypt） |
| `requirements.txt`     | 移除 `passlib[bcrypt]` 依赖         |
| `reset_db.bat`         | 新增数据库重置脚本                  |

---

## 新密码哈希方式

已从 `bcrypt` 改为 `pbkdf2_hmac`，更加安全且无 72 字节限制：

```python
def get_password_hash(password: str) -> str:
    salt = secrets.token_hex(32)
    return salt + ":" + hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000,
    ).hex()
```

---

## 验证修复

**1. 启动后端不应出现错误**

```bash
# 应该看到
INFO:     Started server process [xxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**2. 登录应该正常工作**

- 访问 `http://localhost:5173`
- 使用 `admin / admin123` 登录
- 应该成功跳转到首页

**3. 数据库应该包含用户表**

```sql
-- 可以用 SQLite 客户端查看
SELECT * FROM users;
```

应该显示：

- admin 用户（角色：admin）
- demo 用户（角色：user）

---

## 如果仍有问题

### 1. 清除 Python 缓存

```bash
cd D:\Carbon_AI_Project\carbon_ai
pycache
__pycache__
pip cache purge
```

### 2. 重新创建虚拟环境（如果使用 venv）

```bash
cd D:\Carbon_AI_Project
rmdir /s venv
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 使用 Anaconda Prompt 而非 PowerShell

确保在 `Anaconda Prompt` 中运行，而不是普通 PowerShell。

---

## 下一步

数据库重置后需要：

1. ✅ 重新上传知识文档（如果之前上传过）
2. ✅ 重新创建项目
3. ✅ 重新填写碳排放数据

**注意：** 所有已录入的数据都会丢失，这是正常的。

---

修复完成后，登录系统应该完全正常工作！
