# RecruitFlow 技术规格

## 1. 技术基线

- Runtime：Python 3.12。
- Web：FastAPI、Uvicorn、Jinja2。
- ORM：SQLAlchemy 2.x，迁移使用 Alembic。
- Database：MySQL 8，业务库固定为 `hr_recruitment`。
- Validation：Pydantic 2.x。
- AI：LangChain 1.x、LangGraph 1.x、`langchain-openai`。
- Resume：PyMuPDF、python-docx。
- Frontend：HTMX 或原生 Fetch、原生 CSS、ECharts。
- Export：openpyxl。
- Test：pytest、FastAPI TestClient/httpx。

现有 `agent` 虚拟环境是版本事实来源。附件包清单仅作参考，不得以其旧版本覆盖当前环境。

## 2. 逻辑架构

```text
Browser / WeCom / Demo Simulator
              │
         FastAPI Routers
              │
   Auth / Candidate / Interview / Agent / Inbound / Dashboard
              │
         Application Services
              │
 Repositories ─ LangGraph ─ Adapter Interfaces ─ Background Poller
      │             │              │
   MySQL       SQLite Checkpoint    Excel / Tencent Docs / WeCom
```

MySQL 保存业务事实；LangGraph SQLite Checkpointer 只保存图执行状态，不作为业务数据源。审批恢复时必须同时验证 MySQL 中的审批状态和目标对象版本。

## 3. 建议目录

```text
backend/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── dependencies.py
│   ├── models/
│   ├── schemas/
│   ├── routers/
│   ├── services/
│   ├── repositories/
│   ├── agent/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── nodes.py
│   │   ├── tools.py
│   │   └── prompts.py
│   ├── adapters/
│   │   ├── message_sources.py
│   │   ├── document_sinks.py
│   │   └── notifiers.py
│   ├── templates/
│   ├── static/
│   └── workers/
├── alembic/
├── tests/
├── requirements.txt
└── .env.example
```

Router 只负责协议、鉴权和 Schema；Service 负责事务与业务规则；Repository 只负责 ORM 查询；Agent Tool 必须调用 Service，不能绕过 Service 直接写表。

## 4. 配置

应用只读取根目录或 `backend/` 下的 `.env`，不得读取原始 Markdown 中的密钥。配置分组如下：

```dotenv
APP_NAME=RecruitFlow
APP_ENV=development
DEBUG=false
APP_TIMEZONE=Asia/Shanghai
SECRET_KEY=replace-me
ACCESS_TOKEN_EXPIRE_MINUTES=480

DB_HOST=localhost
DB_PORT=3306
DB_NAME=hr_recruitment
DB_USERNAME=root
DB_PASSWORD=replace-me
DB_CHARSET=utf8mb4
TEST_DB_NAME=hr_recruitment_test

LLM_API_KEY=replace-me
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.7-max-2026-06-08
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2

LANGGRAPH_CHECKPOINT_PATH=./data/langgraph_checkpoints.sqlite
UPLOAD_DIR=./data/uploads
EXPORT_DIR=./data/exports
MAX_RESUME_SIZE_MB=10

WECOM_ENABLED=false
TENCENT_DOCS_ENABLED=false
```

启动时若 `DB_NAME=langchain_db` 或测试数据库等于生产业务库，应用必须拒绝启动。

## 5. 认证与授权

- 登录凭证为用户名和密码；密码使用 bcrypt 哈希，禁止明文保存。
- JWT 放在 `HttpOnly`、`SameSite=Lax` Cookie；生产 HTTPS 时启用 `Secure`。
- API 同时接受同一 Cookie，不为 MVP 开放第三方 token 签发。
- 失败登录返回统一提示，连续 5 次失败后锁定 15 分钟。
- CSRF：所有 Cookie 鉴权的修改请求必须校验 CSRF token。
- Service 层再次校验对象级权限，不能只依赖页面隐藏按钮。

角色权限以 [API 契约](./appendices/api-contract.md) 为准。

## 6. 数据事务和并发

- 一次业务动作的主数据、状态历史、审计日志和同步任务在同一 MySQL 事务中提交。
- 外部文档写入和通知发送不在主事务中执行，由后台 Poller 处理。
- `candidate_jobs`、`approval_requests` 使用整数 `version` 做乐观锁。
- 审批批准时以 `approval_id + version + status=pending` 条件更新；受影响行数为 0 即视为重复或冲突。
- API 不跨请求持有数据库事务。

## 7. 招聘状态机

允许的常规前向路径：

```text
new → screening → interview_1 → interview_2 → final_interview → offer → hired
```

补充规则：

- `interview_1` 可直接进入 `final_interview`；`interview_2` 可进入 `offer`。
- 活跃阶段可进入 `on_hold`；从 `on_hold` 恢复必须由 HR/Admin 明确选择目标活跃阶段。
- 任意非终态可提议 `rejected` 或 `withdrawn`，但必须审批。
- `offer`、`hired` 必须审批。
- `hired`、`rejected`、`withdrawn` 的恢复只允许 Admin 审批。
- 跳过未允许阶段、倒退阶段或目标对象版本变化时，不能自动执行。

自动常规推进同时满足：

- AI 置信度 `>= 0.85`；
- 候选人与应聘关系唯一匹配；
- 目标阶段在允许路径中；
- 当前岗位未关闭；
- 请求用户或消息来源具备权限；
- 不属于高风险或批量操作。

## 8. 简历处理

1. 流式接收文件，同时计算 SHA-256，不把整个大文件读入内存。
2. 校验文件头、MIME、扩展名和 10 MB 上限。
3. 文件保存为内部 UUID 文件名，不使用原始文件名作为路径。
4. PDF 用 PyMuPDF、DOCX 用 python-docx 提取文本。
5. 提取文本不足 100 个非空字符时标记 `unsupported_scanned_document`。
6. 调用模型 Structured Output，输出固定 Pydantic Schema。
7. 保存原始解析结果和人工修订结果，两者不可互相覆盖。
8. 模型失败最多重试 2 次；失败记录为 `failed`，由 HR 手动重试。

Prompt 必须声明：只提取简历事实，不推断年龄、民族、婚育、宗教、健康等敏感属性。

## 9. LangGraph 设计

### 9.1 State

```python
class RecruitmentAgentState(TypedDict):
    thread_id: str
    user_id: str
    message: str
    intent: str | None
    extracted_data: dict | None
    candidate_matches: list[dict]
    selected_tool: str | None
    tool_input: dict | None
    risk_level: str | None
    approval_id: str | None
    result: dict | None
    error: dict | None
```

不得在 State 中保存 API Key、密码、完整简历文件或未脱敏的大批候选人数据。

### 9.2 图节点

```text
START
 → classify_intent
 → extract_entities
 → retrieve_context
 → select_tool
 → validate_tool_input
 → assess_risk
 → [execute_tool | create_approval_and_interrupt]
 → write_audit
 → enqueue_sync
 → format_response
→ END
```

实际 V2 节点固定为：`load_context → classify_and_extract → resolve_entities → plan_and_validate → execute_tools → update_memory → compose_response`。图在进程内惰性编译一次；MySQL 保存展示消息、会话摘要、偏好和工具运行审计，SQLite Checkpointer 只保存可恢复的编排状态。

- 只读意图最低置信度 `0.75`，写意图最低置信度 `0.85`。
- 每轮最多 3 个白名单工具并且最多一个写工具。
- 同名候选人、一人多岗位、超过 10 个用户轮次的历史指代和缺失必填字段均返回可选择的澄清卡片。
- Qwen `json_mode` 提示必须显式包含 JSON 及完整 `IntentResult` JSON Schema，返回值通过 Pydantic 严格校验后才能规划工具。

- 查询工具执行后不创建同步任务。
- `create_approval_and_interrupt` 先提交审批记录，再保存 Checkpoint。
- 审批通过后恢复图时，真正的业务执行必须具备新的幂等键。
- 节点异常写入 `agent_messages` 的错误摘要，但不记录思维链或敏感 Prompt。

### 9.3 模型故障策略

- 超时、限流：指数退避重试，最多 2 次。
- 非法结构：把 Pydantic 校验错误反馈给模型修复 1 次。
- 仍失败：返回 `AI_TEMPORARILY_UNAVAILABLE`，不执行修改。
- 查询场景可提示用户使用页面筛选；修改场景不得规则猜测后执行。

## 10. 入站消息

统一内部事件：

```json
{
  "source": "demo|wecom",
  "external_event_id": "string",
  "sender_external_id": "string",
  "room_external_id": "string|null",
  "message_type": "text",
  "content": "string",
  "occurred_at": "ISO-8601",
  "raw_payload": {}
}
```

- Demo 端点由登录 HR/Admin 调用。
- 企业微信适配器负责签名验证、解密和格式转换；未配置时返回 `INTEGRATION_DISABLED`。
- 只处理文本消息。其他类型保存元数据并标记 `unsupported`，不下载附件。
- 入站事件先落库，再异步/后台处理；重复事件返回已有处理结果。

## 11. 文档同步与通知

接口协议：

```python
class DocumentSink(Protocol):
    def healthcheck(self) -> HealthResult: ...
    def upsert_application(self, payload: ApplicationSyncPayload) -> SyncResult: ...
    def append_event(self, payload: EventSyncPayload) -> SyncResult: ...
```

- `LocalExcelSink` 为默认实现，按 `candidate_job_id` 更新固定工作表中的行。
- `TencentDocsSink` 只在配置完整时启用；凭证缺失不得伪装成功。
- 每个同步任务最多重试 3 次，退避为 1、5、15 分钟。
- 外部同步失败不回滚业务数据，Dashboard 显示失败数量。
- 通知 Poller 每分钟查询到期 `pending` 任务，以 `notification.id` 做幂等。

## 12. Dashboard

统计直接从 MySQL 聚合，不让模型生成 SQL。指标包括：

- 各阶段候选人数量；
- 岗位目标、在招人数和阶段分布；
- 渠道来源分布；
- 相邻阶段转化率；
- 平均阶段停留时间；
- 未来 7 天面试与逾期待办；
- 待审批和同步失败数量。

页面在修改成功后重新请求指标；可使用 SSE 发送“数据已变化”事件，但 SSE 消息不携带候选人敏感数据。

## 13. 错误、日志和审计

- API 错误使用稳定业务码，不向客户端返回堆栈或 SQL。
- 每个请求生成 `request_id`，贯穿日志、审计、Agent 和同步任务。
- 日志使用结构化 JSON；手机号、邮箱、身份证、Token 和模型 Key 必须脱敏。
- `audit_logs` 保存动作、对象、修改前后摘要、来源和操作者，不保存密码与文件正文。
- 健康检查分为 `/health/live` 和 `/health/ready`；ready 检查业务库，不强制外部集成在线。

## 14. 安全约束

- `.env`、上传文件、导出文件、SQLite Checkpoint 和测试报告不得提交到版本库。
- 文件读取必须阻止路径穿越和压缩包炸弹；MVP 不接受 ZIP。
- Jinja2 默认转义；消息、简历和反馈均视为不可信输入。
- Agent Tool 使用 Pydantic 入参，不接受字段之外的内容。
- 所有查询分页并限制最大 `page_size=100`；Agent 最大返回 20 条。
- 原始候选人数据不得用于未经批准的外部模型训练。

## 15. 新增直接依赖

在当前环境基础上只补充：

- `alembic`：数据库迁移；
- `email-validator`：Pydantic EmailStr；
- `aiosqlite`：异步 SQLite；
- `langgraph-checkpoint-sqlite`：持久化图状态。

最终 `requirements.txt` 只锁定项目直接依赖及版本；保留一份环境快照用于复现，但不把附件中的全量旧包清单当作锁文件。

## 16. 部署与启动

- MVP 单进程 Uvicorn 运行，确保后台 Poller 只启动一次。
- Docker 容器端口固定为 8000，挂载 `data/` 保存上传、导出和 Checkpoint。
- MySQL 使用独立数据库和最小权限账号；本地可暂用现有实例，但提交材料不得包含密码。
- 启动顺序：校验配置 → 检查数据库名 → 执行/检查迁移 → 初始化种子账号 → 启动 Poller → 接收请求。
