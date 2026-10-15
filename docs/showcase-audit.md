# 求职展示审计（2026-10-15）

审计基线：`feat/ai-debug-agent-v1` / `ca02402a004ce8c9138f9fc4946774ae5b292466`。
开始时工作区干净；本次修改留在本地，没有提交、推送、合并或变更正式数据库。

## 历史与当前证据

2026-10-14 的 [验收记录](验收记录.md) 描述 Windows/Linux 各 101 项测试和一个真实模型修复加法 Bug 的受控 Demo。
记录与当前 Tool Calling、审批、Worker、worktree、固定 pytest 和验证成功条件一致。
本次先复跑原套件得到 101 passed；没有重新调用付费模型，也没有把历史 Demo 当成新实测或通用修复率。

## 本次修复

原 `Sandbox.run` 的 finally 先调用 `docker rm`，若它超时或抛 OSError，会跳过 kill/wait/管道关闭。
新增回归在修复前 16 failed；最小修复让本地进程回收独立于 Docker 删除结果。
显式删除统一负责容器生命周期，不再与 `--rm` 自动删除竞争；启动、读线程启动及 kill 异常也进入清理。
清理失败记录生成的容器名，不泄露命令原始输出；没有原始异常时抛 `SandboxCleanupError`，已有取消/超时保持其原始类型。
Docker 服务不可用时仍不能保证容器已删除，操作员需要按日志检查；没有宣称实现崩溃自动恢复。

## 实际命令与结果

| 环境 / 检查 | 命令 | 结果 |
| --- | --- | --- |
| Windows Python 3.14.6，原基线 | `python -B -m pytest -q -p no:cacheprovider` | 101 passed，1 warning |
| 修复前复现 | `python -B -m pytest tests/test_sandbox_cleanup.py -q -p no:cacheprovider --tb=no` | 16 failed（预期复现） |
| Windows，最终完整套件 | `python -B -m pytest -q -p no:cacheprovider` | 122 passed，1 warning，19.37s |
| WSL Ubuntu Python 3.12，最终完整套件 | `python -B -m pytest tests -q -p no:cacheprovider` | 122 passed，1 warning，14.00s |
| 依赖 | `python -m pip check` | No broken requirements found |
| 真实 runsc，无 LLM | `python -B scripts/check_sandbox.py`（配置已有固定镜像 ID） | security 1 passed；cancelled=true；timeout=61.4s |
| 容器残留 | `docker ps -a --filter name=bugflow-` | 无匹配容器 |
| Diff | `git diff --check` | 通过 |

warning 为 Starlette/httpx TestClient 弃用提示；未为消除警告升级业务依赖。
122 = 原 101 + 清理回归 21。离线用例的模型/进程替身不是实际模型修复证据。
真实 runsc 检查只使用临时源文件，未调用 LLM，未访问正式数据库。

正式 `bugflow.db` SHA-256 前后仍为
`E15411FF9A55C7B639E3F40CF39025C8D406D23ECB68FACABC65E99485B642B1`。
受跟踪文件无数据库/真实 .env；当前文件与 Git 历史常见密钥模式扫描未命中。
这不是完整 DLP 或依赖漏洞扫描；部分依赖未锁精确版本，未来安装可能产生漂移。

## CI 与合并评估

新增 Windows/Linux × Python 3.12/3.14 离线 pytest 工作流，权限只读，10 分钟上限。
仅用公开测试 JWT 占位值、内存 SQLite、假模型；不引用 GitHub Secrets，不运行付费模型或 Docker。
工作流未推送，所以 GitHub Actions 的云端结果未验证；本地覆盖 Windows 3.14 与 Linux 3.12 两个组合。

只读远程核查：main 为 `92370e0`，Agent 为 `ca02402`；main 是 Agent 分支祖先，无历史分叉。
可以在用户审查本地补丁、提交后 CI 通过时考虑合并。合并后应修订首页分支说明；本次未执行合并。
原业务测试全部保留、通过，启动没有自动建表；Agent 表需操作者显式初始化。
如坚持 main 永远只展示原业务，继续保留分支并在简历链接指定 Agent 分支即可。

## 展示边界

可展示真实业务工具、有限 Agent Loop、后端授权与状态机、Git 补丁证据、受限执行和异常回归。
不可宣称生产级自主修复、多租户安全认证、广泛修复成功率、分布式调度或崩溃恢复。
模型 API 是可选功能；配置自己的 Key 前须评估仓库内容发送给模型服务的授权与预算。


## 试投前再次复核（2026-10-15）

- 只读远程查询：Agent 分支仍为 `ca02402a004ce8c9138f9fc4946774ae5b292466`，main 仍为 `92370e0`；与本地 HEAD 一致，main 是祖先，没有远程分叉。修复、回归、CI 和本次文档仍未提交或推送。
- 发现 CI 环境将 `BUGFLOW_LLM_BASE_URL` 显式设置为空，导致两项使用 MockTransport 的传输测试在配置校验时失败。最小修复为合法 HTTPS 占位地址 `https://offline.invalid/v1`；API Key 和模型名仍为空，不引入真实模型调用。
- 首轮受限 Windows 会话还遇到 pytest 默认临时目录访问拒绝；改用独立临时目录后验证，不修改业务实现或放宽测试断言。
- Windows Python 3.14.6：`python -B -m pytest -q -p no:cacheprovider --basetemp <独立临时目录> --tb=short`，122 passed，1 warning，21.83s；`pip check` 通过。
- Linux Python 3.12.3（已有 WSL2 环境）：`python -B -m pytest tests -q -p no:cacheprovider --tb=short`，122 passed，1 warning，10.87s。
- 两次完整离线验证均使用内存 SQLite、空真实模型凭据及 HTTPS 测试占位地址，没有运行 live_acceptance、Docker/runsc 或付费服务。清理回归仍为 21 项；单次真实模型演示仅引用 2026-10-14 的历史验收。
- `.gitignore` 检查、候选文件和 Git 历史常见凭据模式扫描未发现真实密钥或受跟踪数据库；命中含用户名密码的 URL 是明确的无效配置测试。该检查不替代完整密钥检测或安全认证。
- GitHub Actions 尚未推送，四个矩阵组合的云端结果仍待确认后提交、推送再核实；本地只重新验证 Windows 3.14 / Linux 3.12。
