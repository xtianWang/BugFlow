# BugFlow

BugFlow 是一个面向个人开发者和小型开发团队的轻量 Issue 管理后端。它将项目、成员与 Issue 集中管理，提供认证、权限控制和可追踪的 Issue 状态流转，帮助小团队明确任务归属与处理进度。

## 核心功能

- 用户注册与登录
- JWT Bearer 身份认证与当前用户查询
- Project 创建、查询、部分更新和删除
- Owner / Member / Outsider 项目权限控制
- 项目成员添加、查询和移除
- Issue 创建、查询、部分更新和删除
- assignee 必须是项目中的活跃成员
- Issue priority：`low`、`medium`、`high`、`urgent`
- Issue 状态流转
- pytest API 自动化测试

## Issue 状态流转

```text
open -> in_progress -> resolved -> closed
```

状态只能按上述顺序推进，Owner 与 Member 均可推进合法状态；Outsider 无权访问项目中的 Issue。

## 权限说明

| 操作 | Owner | Member | Outsider |
| --- | --- | --- | --- |
| 查看项目、成员与 Issue | 可以 | 可以 | 不可以 |
| 创建和更新 Issue | 可以 | 可以 | 不可以 |
| 推进合法 Issue 状态 | 可以 | 可以 | 不可以 |
| 管理项目资料和成员 | 可以 | 不可以 | 不可以 |
| 删除 Project 或 Issue | 可以 | 不可以 | 不可以 |

创建 Project 的用户为 Owner，并会自动成为该项目的成员。

## 技术栈

- Python
- FastAPI
- SQLAlchemy
- Pydantic
- SQLite
- PyJWT
- pwdlib / Argon2
- pytest

## 项目结构

```text
app/
  main.py           # FastAPI 应用与路由注册
  config.py         # 环境变量配置
  database.py       # SQLAlchemy engine、Base、Session 依赖
  models.py         # User、Project、ProjectMember、Issue ORM 模型
  schemas.py        # Pydantic 请求与响应模型
  security.py       # 密码哈希与 JWT 创建
  dependencies.py   # 当前用户认证依赖
  permissions.py    # 项目与 Issue 权限校验
  routers/          # auth、projects、issues API 路由

tests/
  conftest.py       # 内存 SQLite 测试数据库与依赖覆盖
  test_auth.py      # 认证 API 测试
  test_projects.py  # 项目 API 测试
  test_issues.py    # Issue API 测试
```

## 本地运行

创建并激活虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

设置本地开发 JWT 密钥。不要将真实密钥提交到 Git：

```powershell
$env:BUGFLOW_SECRET_KEY = "replace-with-a-local-secret"
```

可选配置：

- `BUGFLOW_DATABASE_URL`：默认 `sqlite:///bugflow.db`
- `BUGFLOW_ACCESS_TOKEN_EXPIRE_MINUTES`：默认 `30`，必须为正整数

启动服务：

```powershell
uvicorn app.main:app --reload
```

## API 文档

服务启动后访问 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) 查看交互式 API 文档。

## 测试

```powershell
pytest -v
```

测试使用隔离的内存 SQLite 数据库，并通过 FastAPI `dependency_overrides` 替换正式数据库依赖，因此不会污染开发使用的 `bugflow.db`。

## 当前版本范围

BugFlow v1 暂不包含：

- Comment
- Notification
- 文件上传
- AI 功能
- Redis / Kafka
- 微服务
