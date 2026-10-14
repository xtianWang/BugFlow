# BugFlow

AI Debug Agent V1 扩展见 [运行、架构、接口与验收边界](docs/agent-v1.md)。
原有业务 v1 保留；Agent 已于 2026-10-14 通过真实模型 + 本机 WSL2/runsc 的小型修复验收，
Windows 与 Linux 均为 101 项测试通过。验收范围和限制见 [验收记录](docs/验收记录.md)。

### 使用自己的模型服务

在启动后端的同一个 PowerShell 窗口设置以下环境变量：

```powershell
$env:BUGFLOW_LLM_BASE_URL = 'https://你的兼容服务地址/v1'
$env:BUGFLOW_LLM_MODEL = '服务商提供的支持工具调用的模型名'
$env:BUGFLOW_LLM_API_KEY = Read-Host '输入你自己的 API Key' -MaskInput
```

`-MaskInput` 需要 PowerShell 7.1+；其他环境请使用运行平台的密钥注入功能。
Key 只交给后端，不放进前端请求、代码或 Git。`.env.example` 只是示例，应用不会自动加载 `.env`。
地址填写 API 基础路径，不要附加 `/chat/completions`、查询参数或用户名密码。
当前适配器要求 HTTPS、Bearer 认证及兼容 Chat Completions 的 `tools`、`tool_choice`、`max_tokens`。
启动后的进程不会自动获得另一个终端新设置的变量，修改终端配置后请重启后端和 worker。

DeepSeek 当前验收使用 `https://api.deepseek.com`、`deepseek-flash`，另设
`$env:BUGFLOW_LLM_THINKING = 'disabled'` 显式关闭思考模式。
该配置只接受空值（不发送此字段）或 `disabled`；其他服务不需要时保持未设置。

每个 LLM 实例首次使用工具会做一次无业务数据的 `tool_choice=required` 探测，成功后仍允许普通文本回答。
探测增加一次模型请求和少量费用，不代表该模型的调试能力已经验收。
缺少配置返回 `503 llm_not_configured`；非法配置返回 `503 llm_invalid_config`；
提供商认证失败、不支持工具或返回异常等返回带分类错误码的 `502`，不返回提供商原始错误内容。

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
- 原始业务 v1 不包含 AI；可选 Agent 扩展范围与限制见上方文档
- Redis / Kafka
- 微服务
