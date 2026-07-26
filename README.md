# RecruitFlow — AI 招聘运营平台

RecruitFlow 是一个可直接演示的 AI 招聘运营平台，将简历、候选人、岗位、面试、群消息、审批、通知和招聘看板连接为一条可审计的数据链路。

[Python 3.12] [FastAPI] [MySQL 8] [LangGraph] [Docker]

---

## 目录

- [1. 功能介绍](#1-功能介绍)
  - [1.1 核心能力](#11-核心能力)
  - [1.2 技术架构](#12-技术架构)
  - [1.3 项目结构](#13-项目结构)
- [2. 快速开始](#2-快速开始)
  - [2.1 环境要求](#21-环境要求)
  - [2.2 配置与初始化](#22-配置与初始化)
  - [2.3 启动服务](#23-启动服务)
  - [2.4 演示账号](#24-演示账号)
- [3. 开发指南](#3-开发指南)
  - [3.1 开发环境搭建](#31-开发环境搭建)
  - [3.2 数据库迁移](#32-数据库迁移)
  - [3.3 新增 Agent 工具](#33-新增-agent-工具)
  - [3.4 完整配置参考](#34-完整配置参考)
- [4. 测试](#4-测试)
  - [4.1 单元测试与 API 测试](#41-单元测试与-api-测试)
  - [4.2 真实模型集成测试](#42-真实模型集成测试)
  - [4.3 Agent 场景评测](#43-agent-场景评测)
- [5. 部署](#5-部署)
  - [5.1 Docker Compose](#51-docker-compose)
  - [5.2 Cloudflare Tunnel 公网访问](#52-cloudflare-tunnel-公网访问)
- [6. API 文档](#6-api-文档)
- [7. 面试演示路径](#7-面试演示路径)
- [8. 安全注意事项](#8-安全注意事项)

---

## 1. 功能介绍

### 1.1 核心能力

| 模块 | 能力 |
|---|---|
| **简历解析** | PDF / DOCX / 图片文本提取，Qwen Structured Output 结构化解析，无模型 Key 时自动降级为规则解析 |
| **候选人管理** | 15 张业务表，以"候选人 × 岗位"为唯一事实，完整状态流转（新建 → 筛选 → 一面 → 二面 → 终面 → Offer → 入职/淘汰） |
| **面试管理** | 面试安排、反馈记录、状态自动推进，面试前 24 小时提醒 |
| **权限与审批** | `admin / hr / interviewer` 三级角色，Human-in-the-loop 审批流程，高风险操作必须人工确认 |
| **AI 招聘助手 V2** | LangGraph Agent，13 种意图识别，11 个白名单工具，每轮最多 3 步、最多 1 个写操作 |
| **消息自动化** | 企业微信群消息模拟、幂等处理、自动/审批分流 |
| **数据同步** | 本地 Excel 实时同步、失败重试、同步任务追踪 |
| **招聘看板** | ECharts 招聘漏斗、候选人分布、岗位进度一览 |

### 1.2 技术架构

```
┌──────────────────────────────────────────────────┐
│                    浏览器                          │
│              http://127.0.0.1:8000                │
│           Jinja2 服务端渲染 + ECharts              │
└─────────────────────┬────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────┐
│                  FastAPI (Uvicorn)                 │
│              JWT Cookie + CSRF Token               │
└──┬──────────────┬──────────────┬─────────────────┘
   │              │              │
┌──▼──────┐ ┌─────▼──────┐ ┌───▼───────────┐
│ REST API │ │ Agent V2   │ │ Background    │
│ api.py   │ │ LangGraph  │ │ Worker        │
│ /api/*   │ │ StateGraph │ │ workers.py    │
└──┬───────┘ └─────┬──────┘ └───┬───────────┘
   │               │             │
   │   ┌───────────▼──────────┐  │
   │   │   Intent 分类        │  │
   │   │   Qwen / DeepSeek    │  │
   │   │   + 规则降级          │  │
   │   └──────────────────────┘  │
   │               │             │
┌──▼───────────────▼─────────────▼───────────┐
│              MySQL 8.0                      │
│  主库: hr_recruitment  │  测试库: hr_recruitment_test │
│  + SQLite (LangGraph checkpoint)           │
└─────────────────────────────────────────────┘
```

| 层级 | 技术 | 说明 |
|---|---|---|
| Web 框架 | FastAPI 0.135 | 异步路由、依赖注入、自动 OpenAPI |
| 服务端渲染 | Jinja2 + ECharts | 工作台、看板、Agent 对话界面 |
| ORM | SQLAlchemy 2.0 + Alembic | 15 张业务表、幂等迁移 |
| 认证 | PyJWT + bcrypt | Cookie JWT、CSRF、角色鉴权 |
| Agent | LangGraph 1.1 + langgraph-checkpoint-sqlite | 多步状态图、意图分类、工具执行 |
| LLM | 通义千问 (DashScope) / DeepSeek | OpenAI 兼容协议、可选 thinking 模式 |
| 简历解析 | PyMuPDF + python-docx + 阿里云 OCR | PDF/DOCX/图片文本提取与结构化 |
| 容器化 | Docker + Docker Compose | MySQL + App 双服务编排 |

### 1.3 项目结构

```
AA_hragent/
├── backend/                         # 应用主目录
│   ├── app/
│   │   ├── main.py                  # FastAPI 入口、Jinja2 路由、生命周期
│   │   ├── api.py                   # 全部 REST API 端点 (/api/*)
│   │   ├── config.py                # Settings 数据类（读取 .env）
│   │   ├── database.py              # SQLAlchemy 引擎、SQL 追踪
│   │   ├── models.py                # 15 张 ORM 模型
│   │   ├── schemas.py               # Pydantic 请求/响应模型
│   │   ├── security.py              # JWT、bcrypt、CSRF、角色依赖
│   │   ├── services.py              # 业务逻辑层
│   │   ├── repositories.py          # 查询辅助（分页、搜索）
│   │   ├── ocr.py                   # 阿里云 OCR 客户端
│   │   ├── workers.py               # 后台 Worker（Excel 同步 + 通知轮询）
│   │   ├── ui_labels.py             # 中文 UI 标签
│   │   ├── agent/                   # AI Agent 模块 (V2)
│   │   │   ├── types.py             # 意图枚举、实体抽取、工具定义
│   │   │   ├── graph.py             # LangGraph 状态图、工具实现
│   │   │   ├── intelligence.py      # LLM 意图分类 + 安全规则降级
│   │   │   ├── policy.py            # 工具白名单、计划构建、校验
│   │   │   ├── runtime.py           # V2 Agent 运行时编排
│   │   │   ├── memory.py            # 会话记忆、偏好管理、脱敏
│   │   │   ├── response.py          # 回答卡片、自然语言润色
│   │   │   ├── trace.py             # JSONL 追踪记录
│   │   │   └── evaluation.py        # 评测场景类型定义
│   │   ├── static/                  # CSS 样式
│   │   └── templates/               # Jinja2 HTML 模板
│   ├── alembic/                     # 数据库迁移
│   │   ├── env.py
│   │   └── versions/                # 4 个迁移文件
│   ├── scripts/                     # 工具脚本
│   │   ├── seed.py                  # 演示数据播种
│   │   ├── create_databases.py      # 创建数据库
│   │   ├── reset_test_database.py   # 重置测试库
│   │   ├── generate_demo_data.py    # 生成虚构招聘数据
│   │   ├── generate_agent_scenarios.py  # 生成 Agent 评测场景
│   │   └── run_agent_eval.py        # Agent 评测执行器
│   ├── tests/                       # pytest 测试套件
│   ├── Dockerfile
│   └── requirements.txt
├── docs/                            # 规格文档
│   ├── DEV_SPEC.md                  # 开发规格主文档
│   ├── 01-product-spec.md           # 产品规格
│   ├── 02-technical-spec.md         # 技术规格
│   ├── 03-implementation-plan.md    # 实施计划
│   └── appendices/                  # 附录（数据库 Schema、API 合约、验收矩阵）
├── docker-compose.yml
├── bootstrap.ps1                    # 一键初始化脚本
├── run.ps1                          # 启动开发服务器
├── test.ps1                         # 运行测试套件
├── test-real.ps1                    # 运行真实模型集成测试
├── run-agent-eval.ps1               # 运行 Agent 评测
├── .env.example                     # 环境变量模板
├── .gitignore
└── .dockerignore
```

---

## 2. 快速开始

### 2.1 环境要求

- **操作系统**：Windows（开发）、Linux（Docker）
- **Python**：3.12（虚拟环境已内置在 `agent/` 目录）
- **数据库**：MySQL 8.0
- **LLM API Key**（可选）：阿里云百炼 / DeepSeek，不填则使用规则解析降级

### 2.2 配置与初始化

```powershell
# 1. 从模板创建 .env
Copy-Item .env.example .env
```

编辑 `.env`，至少填写以下内容：

```dotenv
# 必填 — JWT 签名密钥
SECRET_KEY=长度至少32字节的随机值

# 必填 — MySQL 数据库凭证
DB_USERNAME=root
DB_PASSWORD=你的本地MySQL密码
DB_NAME=hr_recruitment
TEST_DB_NAME=hr_recruitment_test
```

如需真实 LLM 简历解析和 AI 助手，再填写：

```dotenv
# 阿里云百炼（Qwen 模型）
LLM_API_KEY=你的百炼Key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.7-max-2026-06-08

# 或使用 DeepSeek
DEEPSEEK_API_KEY=你的DeepSeek Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash

# Agent V2
AGENT_V2_ENABLED=true
AGENT_MEMORY_ENABLED=true
```

一键初始化（安装依赖 → 创建数据库 → 迁移 → 播种演示数据）：

```powershell
.\bootstrap.ps1
```

### 2.3 启动服务

```powershell
.\run.ps1
```

访问：<http://127.0.0.1:8000>

### 2.4 演示账号

`.env` 中 `DEMO_PASSWORD` 的值为演示密码（默认为 `RecruitFlow!2026`）：

| 账号 | 角色 | 权限范围 |
|---|---|---|
| `admin_demo` | 管理员 | 全部功能、审批、系统配置 |
| `hr_demo` | HR | 候选人管理、面试安排、消息处理、看板查看 |
| `interviewer_demo` | 面试官 | 查看分配的面试、提交反馈 |

> **生产环境禁止执行 Seed 脚本**，演示账号仅用于本地开发。

---

## 3. 开发指南

### 3.1 开发环境搭建

```powershell
# 1. 克隆仓库
git clone <your-repo-url> RecruitFlow
cd RecruitFlow

# 2. 创建虚拟环境（如不使用内置 agent/）
python -m venv agent
.\agent\Scripts\Activate.ps1
pip install -r backend\requirements.txt

# 3. 配置 .env
Copy-Item .env.example .env
# 编辑 .env 填入数据库密码和可选的 LLM Key

# 4. 初始化
.\bootstrap.ps1

# 5. 启动开发服务器（热重载）
.\run.ps1
```

建议在 VS Code 中设置 `python.defaultInterpreterPath` 指向 `agent/Scripts/python.exe`。

### 3.2 数据库迁移

项目使用 Alembic 管理数据库版本：

```powershell
# 设置环境变量
$env:PYTHONPATH = "$PWD\backend"

# 生成新迁移（Model 变更后）
.\agent\Scripts\python.exe -m alembic -c backend\alembic.ini revision --autogenerate -m "描述你的变更"

# 应用迁移到开发库
.\agent\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head

# 回退一个版本
.\agent\Scripts\python.exe -m alembic -c backend\alembic.ini downgrade -1

# 查看迁移历史
.\agent\Scripts\python.exe -m alembic -c backend\alembic.ini history
```

**注意事项**：
- 迁移文件在 `backend/alembic/versions/`
- `env.py` 会校验数据库边界，拒绝连接受保护的 `langchain_db`
- 测试环境始终使用 `TEST_DB_NAME`（`hr_recruitment_test`）

### 3.3 新增 Agent 工具

Agent V2 的 11 个白名单工具定义在 `backend/app/agent/policy.py` 的 `TOOL_DEFINITIONS` 字典中。新增工具需修改以下文件：

**步骤 1 — 定义工具元数据**（`backend/app/agent/policy.py`）：

```python
# 在 TOOL_DEFINITIONS 中添加
"my_new_tool": ToolDefinition(
    "my_new_tool",
    frozenset({"admin", "hr"}),   # 允许的角色
    "write",                        # side_effect: read / write / external
    "medium",                       # risk_level: low / medium / high
    10,                             # timeout_seconds
    0,                              # max_retries
    True,                           # auto_execute（不需要审批）
)
```

**步骤 2 — 添加意图映射**（`backend/app/agent/types.py` + `policy.py`）：

```python
# types.py — 在 IntentName 枚举中新增意图
class IntentName(str, Enum):
    # ... 现有的 ...
    my_intent = "my_intent"

# policy.py — 在 INTENT_TOOL 中添加映射
INTENT_TOOL = {
    # ... 现有的 ...
    IntentName.my_intent: "my_new_tool",
}
```

**步骤 3 — 实现工具执行逻辑**（`backend/app/agent/runtime.py` 或 `graph.py`）：

在 Agent 状态图的 `execute_tools` 节点中，为新的工具名添加执行分支，调用 `services.py` 或 `repositories.py` 中的业务逻辑。

**步骤 4 — 安全检查**（如有必要，修改 `backend/app/agent/policy.py`）：

- 如果工具是高风险写操作（`risk_level: "high"`），在 `build_plan()` 中添加审批流程分支
- 确保意图分类的 prompt 中包含了新意图的描述（`backend/app/agent/intelligence.py`）

### 3.4 完整配置参考

| 变量 | 说明 | 默认值 | 必填 |
|---|---|---|---|
| **应用配置** | | | |
| `APP_NAME` | 应用名称 | `RecruitFlow` | |
| `APP_ENV` | 运行环境 | `development` | |
| `DEBUG` | 调试模式 | `false` | |
| `APP_TIMEZONE` | 时区 | `Asia/Shanghai` | |
| `SECRET_KEY` | JWT 签名密钥 | — | **🔴 必填** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token 过期时间（分） | `480` | |
| `DEMO_PASSWORD` | 演示账号密码 | `RecruitFlow!2026` | |
| **数据库** | | | |
| `DB_HOST` | MySQL 主机 | `localhost` | **🔴 必填** |
| `DB_PORT` | MySQL 端口 | `3306` | |
| `DB_NAME` | 数据库名（禁止为 `langchain_db`） | `hr_recruitment` | **🔴 必填** |
| `DB_USERNAME` | 数据库用户名 | `root` | **🔴 必填** |
| `DB_PASSWORD` | 数据库密码 | — | **🔴 必填** |
| `DB_CHARSET` | 字符集 | `utf8mb4` | |
| `TEST_DB_NAME` | 测试数据库名 | `hr_recruitment_test` | **🔴 必填** |
| **LLM 配置** | | | |
| `LLM_API_KEY` | 阿里云百炼 API Key | — | 可选 |
| `LLM_BASE_URL` | LLM API 地址 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | |
| `LLM_MODEL` | 模型名称 | `qwen3.7-max-2026-06-08` | |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | — | 可选 |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址 | `https://api.deepseek.com` | |
| `LLM_TIMEOUT_SECONDS` | LLM 请求超时 | `60` | |
| `LLM_MAX_RETRIES` | LLM 请求重试次数 | `2` | |
| `LLM_ENABLE_THINKING` | 启用 Thinking 模式（仅 Qwen） | `false` | |
| `LLM_THINKING_BUDGET` | Thinking Token 预算 | `256` | |
| `RESPONSE_LLM_ENABLED` | 启用回复润色 LLM | `true` | |
| `RESPONSE_LLM_MODEL` | 回复润色专用模型 | 同 `LLM_MODEL` | |
| **Agent V2** | | | |
| `AGENT_V2_ENABLED` | 启用 Agent V2 | `true` | |
| `AGENT_V2_SHADOW_MODE` | 影子模式（V1/V2 并行） | `false` | |
| `AGENT_MEMORY_ENABLED` | 启用会话记忆 | `true` | |
| `AGENT_LLM_ROUTER_ENABLED` | 启用 LLM 路由 | `true` | |
| `AGENT_READ_CONFIDENCE` | 读取操作置信度阈值 | `0.75` | |
| `AGENT_WRITE_CONFIDENCE` | 写入操作置信度阈值 | `0.85` | |
| `AGENT_RECENT_MESSAGE_LIMIT` | 最近消息窗口 | `12` | |
| `AGENT_MAX_TOOL_STEPS` | 每轮最大工具步数 | `3` | |
| `AGENT_PROMPT_VERSION` | Prompt 版本标识 | `recruitflow-agent-v2.0` | |
| `AGENT_TRACE_ENABLED` | 启用追踪记录 | `false` | |
| `AGENT_TRACE_DIR` | 追踪记录目录 | `./backend/data/test-artifacts` | |
| **本地存储** | | | |
| `LANGGRAPH_CHECKPOINT_PATH` | LangGraph Checkpoint 路径 | `./data/langgraph_checkpoints.sqlite` | |
| `UPLOAD_DIR` | 简历上传目录 | `./data/uploads` | |
| `EXPORT_DIR` | Excel 导出目录 | `./data/exports` | |
| `MAX_RESUME_SIZE_MB` | 简历文件大小上限 | `10` | |
| **阿里云 OCR** | | | |
| `ALIYUN_OCR_ENDPOINT` | OCR API 地址 | `https://gjbsb.market.alicloudapi.com/ocrservice/advanced` | |
| `ALIYUN_OCR_APPCODE` | OCR AppCode | — | 可选 |
| `ALIYUN_OCR_TIMEOUT_SECONDS` | OCR 超时 | `20` | |
| **企业微信（默认关闭）** | | | |
| `WECOM_ENABLED` | 启用企业微信 | `false` | |
| `WECOM_CORP_ID` | 企业 ID | — | |
| `WECOM_AGENT_ID` | 应用 AgentId | — | |
| `WECOM_SECRET` | 应用 Secret | — | |
| **腾讯文档（默认关闭）** | | | |
| `TENCENT_DOCS_ENABLED` | 启用腾讯文档 | `false` | |
| **后台与日志** | | | |
| `NOTIFICATION_POLL_SECONDS` | 通知轮询间隔 | `60` | |
| `SYNC_MAX_RETRIES` | 同步最大重试 | `3` | |
| `LOG_LEVEL` | 日志级别 | `INFO` | |
| `BACKGROUND_WORKER_ENABLED` | 启用后台 Worker | `true` | |

---

## 4. 测试

### 4.1 单元测试与 API 测试

不调用外部模型，使用确定性路由，不消耗 LLM 额度：

```powershell
.\test.ps1
```

脚本执行流程：校验数据库凭证 → 重置测试库 → 迁移 → 播种 → `pytest -q`。

测试覆盖：
- API 端点（CRUD、权限、CSRF）
- Agent V2 意图分类与工具执行
- Agent 回复生成与降级
- Agent 评测资产验证
- 阿里云 OCR 客户端
- 回复模型兼容性

### 4.2 真实模型集成测试

使用 `.env` 中的真实 Qwen API Key 和数据库凭证：

```powershell
.\test-real.ps1
```

该脚本仍只写入 `TEST_DB_NAME`（`hr_recruitment_test`），验证真实 Qwen 简历解析以及 Agent 结构化意图与工具调用。日常 `test.ps1` 不调用外部模型。

### 4.3 Agent 场景评测

50 个固定场景、每场景 6 轮对话（35 个 HR 场景 + 15 个面试官场景，共 300 轮）。

**生成场景**：

```powershell
.\agent\Scripts\python.exe backend\scripts\generate_agent_scenarios.py --count 50 --seed 20260726
```

**运行全量评测**：

```powershell
.\run-agent-eval.ps1
```

脚本只允许删除并重建 `hr_recruitment_test`，专用服务固定使用 `127.0.0.1:8011`，不会影响 8000 端口的开发服务。

**进阶用法**：

```powershell
# 单个场景复放
.\run-agent-eval.ps1 --scenario hr_001

# 指定多个场景，并发度为 2
.\run-agent-eval.ps1 --scenario 'hr_001,hr_017,interviewer_006' --concurrency 2

# 断点续跑
.\run-agent-eval.ps1 --resume --run-id eval_20260726_183000

# 按标签筛选，指定并发度（SQLite Checkpoint 最多 5 并发，建议从 2 开始）
.\run-agent-eval.ps1 --tag dashboard --concurrency 2

# 重测历史运行中未通过的场景
.\run-agent-eval.ps1 --rerun-failed-from eval_20260726_193755 --concurrency 2
```

不传 `--concurrency` 时使用顺序基线。

**结果位置**：`backend/data/test-artifacts/<run_id>/`

- `traces.jsonl` — 原始追踪数据
- `*.csv` — 逐轮与逐场景统计
- `report.html` — 离线报告
- `server.out.log` / `server.err.log` — 服务日志

> 日志只记录输入长度、哈希、Token、脱敏业务 ID 和规范化 SQL 哈希，不记录 Prompt、SQL 参数、简历正文、密钥或完整联系方式。
>
> 如果报告显示 `run_complete=false` 或控制台输出 `EVAL_INCOMPLETE_PROVIDER_FAILURE`，说明 LLM 供应商鉴权、额度或模型服务异常导致本轮不完整。处理供应商配置后仅复跑失败场景即可。

---

## 5. 部署

### 5.1 Docker Compose

Docker Compose 会启动独立 MySQL 和应用，自动完成迁移和播种：

```powershell
docker compose up --build
```

| 服务 | 端口 | 说明 |
|---|---|---|
| `mysql` | `3307:3306` | MySQL 8.0，健康检查 + 命名卷持久化 |
| `app` | `8000:8000` | FastAPI，自动迁移 + 播种 |

> 请先创建 `.env`，不要提交密钥。Docker 模式下 `DB_HOST` 会被覆盖为 `mysql`（容器内服务名）。

### 5.2 Cloudflare Tunnel 公网访问

如需实现固定域名的公网访问（无需开放路由器端口），可使用 Cloudflare Tunnel（cloudflared）。

优势：免费、内置 SSL、DDoS 防护、支持 CGNAT 环境、无需改动防火墙。

> 完整操作指南见 **[docs/cloudflare-tunnel.md](docs/cloudflare-tunnel.md)**（待创建）。

简要步骤：

1. 将域名 DNS 托管到 Cloudflare
2. 安装 `cloudflared`：`winget install cloudflared`
3. 创建 Tunnel：`cloudflared tunnel create recruitflow`
4. 配置 DNS：`cloudflared tunnel route dns recruitflow hr.你的域名.com`
5. 编写 `config.yml` 指向 `http://localhost:8000`
6. 注册 Windows 服务：`cloudflared service install`

---

## 6. API 文档

启动服务后访问：

- **Swagger UI**：<http://127.0.0.1:8000/docs>
- **健康检查**：`/health/live`、`/health/ready`

### 主要接口

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/auth/login` | POST | 登录（返回 JWT Cookie + CSRF Token） |
| `/api/auth/logout` | POST | 登出 |
| `/api/auth/me` | GET | 当前用户信息 |
| `/api/candidates` | GET / POST | 候选人列表 / 新建 |
| `/api/candidates/{id}` | GET / PATCH | 候选人详情 / 更新 |
| `/api/candidates/import-resume` | POST | 简历导入 |
| `/api/jobs` | GET / POST | 岗位列表 / 新建 |
| `/api/jobs/{id}` | GET / PATCH | 岗位详情 / 更新 |
| `/api/interviews` | GET / POST | 面试列表 / 安排面试 |
| `/api/interviews/{id}/feedback` | POST | 提交面试反馈 |
| `/api/approvals` | GET | 审批列表 |
| `/api/approvals/{id}/approve` | POST | 批准 |
| `/api/approvals/{id}/reject` | POST | 驳回 |
| `/api/agent/chat` | POST | AI 助手对话 |
| `/api/agent/conversations` | GET | 会话列表 |
| `/api/agent/conversations/{id}/memory` | GET / DELETE | 查看/清除会话记忆 |
| `/api/agent/preferences` | GET / POST | 用户偏好管理 |
| `/api/dashboard` | GET | 招聘看板数据 |
| `/api/inbound/demo` | POST | 模拟群消息 |
| `/api/notifications` | GET | 通知列表 |

所有 Cookie 鉴权的修改请求需要 `X-CSRF-Token` 请求头，其值来自登录后设置的 `csrf_token` Cookie。

完整 API 合约详见 [docs/appendices/api-contract.md](docs/appendices/api-contract.md)。

---

## 7. 面试演示路径

按以下步骤展示平台核心价值：

1. 使用 `hr_demo` 登录，查看 Dashboard 招聘漏斗
2. 进入「消息自动化」，发送"李明一面通过，安排二面"
3. 查看候选人「李明」的应聘阶段自动推进，以及 Excel 同步任务状态
4. 发送"王芳终面不通过，建议淘汰"
5. 进入「审批中心」，确认 AI **没有**直接淘汰候选人，而是创建了待审批记录
6. 批准审批后，刷新 Dashboard 确认数据更新
7. 在「AI 招聘助手」中询问"目前有多少开放岗位和待审批？"

**演示要点**：AI 只是辅助决策，所有高风险操作必须经过 Human-in-the-loop 审批。

---

## 8. 安全注意事项

### 8.1 API Key 管理

- **`.env` 绝对不能提交到 Git**（已在 `.gitignore` 中排除）
- **`.claude/settings.json` 和 `.claude/settings.local.json`** 可能包含 API Token，同样已排除
- 所有 API Key 应通过环境变量注入，禁止在源代码中硬编码
- `.env.example` 是模板文件，只包含占位符，可以安全提交

### 8.2 生产环境检查清单

部署到生产环境前，务必完成以下检查：

- [ ] `SECRET_KEY` — 修改为 ≥32 字节的随机字符串
- [ ] `DEMO_PASSWORD` — 修改为强密码，或完全禁用演示账号
- [ ] `DB_PASSWORD` — 使用强密码，不要使用 `123456`
- [ ] `DEBUG` — 设置为 `false`
- [ ] `APP_ENV` — 设置为 `production`
- [ ] 数据库 — 禁止执行 `seed.py` 和 `generate_demo_data.py`
- [ ] HTTPS — 通过 Cloudflare Tunnel 或反向代理启用 TLS
- [ ] 数据库端口 — 生产环境不要暴露 MySQL 端口到公网
- [ ] Agent 写操作 — 确认高风险操作 (`risk_level: "high"`) 的审批流程正常工作
- [ ] LLM API Key — 确认额度充足，或配置了安全的规则降级

### 8.3 密钥泄露应急处理

如果 API Key 不慎提交到 Git 或公开：

1. **立即轮换**：登录对应平台（阿里云百炼 / DeepSeek / 阿里云 OCR 市场）→ 禁用旧 Key → 生成新 Key
2. **更新 `.env`**：用新 Key 替换
3. **检查 Git 历史**：如果已推送，使用 `git filter-branch` 或 `BFG Repo-Cleaner` 清除历史
4. **检查 API 调用日志**：确认密钥未被恶意使用

---

## 外部集成边界

- 默认 `DemoMessageSource + LocalExcelSink`，无需第三方权限
- 企业微信与腾讯文档配置缺失时明确返回 `disabled`，不伪装真实成功
- 普通群机器人无法读取全部群聊；真实全量消息需要企业管理员配置合规的会话内容存档能力
- 候选人数据不得发送给未经企业批准的外部模型

---

完整规格见 [DEV_SPEC](docs/DEV_SPEC.md)。
