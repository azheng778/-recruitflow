# RecruitFlow API 与 Agent Tool 契约

## 1. 通用协议

### 1.1 路径与格式

- API 前缀：`/api`。
- 请求和响应：`application/json; charset=utf-8`，文件上传除外。
- 时间：带时区的 ISO 8601；服务端转换为 UTC。
- UUID：小写标准字符串。
- 未声明字段：Pydantic 配置 `extra="forbid"`，返回 422。

### 1.2 统一响应

成功：

```json
{
  "success": true,
  "data": {},
  "error": null,
  "request_id": "b99bfc61-82bf-4024-b321-a8df084896b3"
}
```

失败：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "候选人不存在或不可访问",
    "details": {}
  },
  "request_id": "b99bfc61-82bf-4024-b321-a8df084896b3"
}
```

分页：

```json
{
  "page": 1,
  "page_size": 20,
  "total": 38,
  "items": []
}
```

默认 `page=1`、`page_size=20`，最大 `page_size=100`。Agent Tool 最大返回 20 条。

### 1.3 HTTP 与业务错误

| HTTP | 业务码 | 场景 |
|---|---|---|
| 400 | INVALID_REQUEST | 跨字段或业务参数错误 |
| 401 | AUTH_REQUIRED / INVALID_CREDENTIALS | 未登录或凭证错误 |
| 403 | PERMISSION_DENIED / CSRF_FAILED | 角色或对象权限不足 |
| 404 | RESOURCE_NOT_FOUND | 对象不存在、已删除或不可访问 |
| 409 | DUPLICATE_RESOURCE | 唯一键冲突 |
| 409 | VERSION_CONFLICT | 乐观锁或审批目标版本变化 |
| 409 | INVALID_STATUS_TRANSITION | 非法阶段迁移 |
| 413 | FILE_TOO_LARGE | 简历超限 |
| 415 | UNSUPPORTED_FILE_TYPE | 文件类型不支持 |
| 422 | VALIDATION_ERROR | Pydantic 校验失败 |
| 422 | UNSUPPORTED_SCANNED_DOCUMENT | 无可提取文本 |
| 429 | TOO_MANY_REQUESTS | 登录或 AI 接口限流 |
| 503 | AI_TEMPORARILY_UNAVAILABLE | 模型不可用且未执行修改 |
| 503 | INTEGRATION_DISABLED | 外部适配器未配置 |
| 502 | EXTERNAL_SERVICE_ERROR | 外部调用失败 |

## 2. 公共 Schema

### 2.1 枚举

```python
class UserRole(str, Enum):
    admin = "admin"
    hr = "hr"
    interviewer = "interviewer"

class JobStatus(str, Enum):
    draft = "draft"
    open = "open"
    closed = "closed"

class RecruitmentStage(str, Enum):
    new = "new"
    screening = "screening"
    interview_1 = "interview_1"
    interview_2 = "interview_2"
    final_interview = "final_interview"
    on_hold = "on_hold"
    offer = "offer"
    hired = "hired"
    rejected = "rejected"
    withdrawn = "withdrawn"

class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    conflict = "conflict"
    cancelled = "cancelled"
```

### 2.2 候选人

```python
class CandidateCreate(BaseModel):
    name: str                    # 1..100
    phone: str | None = None
    email: EmailStr | None = None
    city: str | None = None
    source: str = "manual"
    current_company: str | None = None
    years_of_experience: Decimal | None = None
    skills: list[str] = []
    education: list[EducationItem] = []
    work_experience: list[WorkItem] = []
    projects: list[ProjectItem] = []
    summary: str | None = None
    job_id: UUID | None = None

class CandidatePatch(BaseModel):
    version: int
    name: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    city: str | None = None
    current_company: str | None = None
    years_of_experience: Decimal | None = None
    skills: list[str] | None = None
    summary: str | None = None
```

Candidate 详情响应包含 `applications`、`resumes`、`interviews`、`communications`、`status_history`，但不返回文件系统路径。列表和面试官视图中的 phone/email 为脱敏值。

### 2.3 状态提议

```python
class StatusChangeProposal(BaseModel):
    candidate_job_id: UUID
    target_status: RecruitmentStage
    reason: str | None = None
    confidence: Decimal | None = None
    version: int
    idempotency_key: str         # 16..64
```

响应：

```json
{
  "execution": "applied|approval_required",
  "candidate_job": {},
  "approval": null
}
```

## 3. 认证 API

| 方法与路径 | 权限 | 请求 | 成功响应 | 副作用/错误 |
|---|---|---|---|---|
| POST `/api/auth/login` | Public | `{username,password,csrf_token}` | 当前用户；设置 JWT Cookie | 记录成功/失败；401；429 |
| POST `/api/auth/logout` | Login | CSRF Header | `{logged_out:true}` | 清 Cookie |
| GET `/api/auth/me` | Login | 无 | 当前用户及 role | 401 |

登录响应和日志不得返回 `password_hash`。连续 5 次失败锁定 15 分钟。

## 4. 岗位 API

### 4.1 Schema

```python
class JobCreate(BaseModel):
    job_code: str
    job_name: str
    department: str
    description: str
    requirements: str
    location: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    headcount: int = 1
    owner_id: UUID
    status: JobStatus = JobStatus.draft

class JobPatch(BaseModel):
    version: int
    job_name: str | None = None
    department: str | None = None
    description: str | None = None
    requirements: str | None = None
    location: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    headcount: int | None = None
    owner_id: UUID | None = None
```

| 方法与路径 | 权限 | 行为 |
|---|---|---|
| GET `/api/jobs` | Admin/HR；Interviewer 只返回关联岗位 | 按 status、department、owner_id、keyword 分页 |
| POST `/api/jobs` | Admin/HR | 创建岗位；job_code 冲突返回 409 |
| GET `/api/jobs/{job_id}` | 有对象权限 | 返回岗位与阶段统计 |
| PATCH `/api/jobs/{job_id}` | Admin/负责 HR | 乐观锁更新 |
| POST `/api/jobs/{job_id}/open` | Admin/负责 HR | draft→open，记录 opened_at |
| POST `/api/jobs/{job_id}/close` | Admin/负责 HR | draft/open→closed；不影响历史 |

关闭岗位后新增应聘关系或面试返回 `JOB_CLOSED`。

## 5. 候选人、应聘关系与简历 API

| 方法与路径 | 权限 | 请求/查询 | 成功响应与副作用 |
|---|---|---|---|
| GET `/api/candidates` | Admin/HR | keyword、job_id、status、source、owner_id、分页 | 脱敏分页列表 |
| POST `/api/candidates` | Admin/HR | CandidateCreate | 创建候选人；含 job_id 时创建应聘关系 |
| GET `/api/candidates/{id}` | Admin/HR；关联 Interviewer 为受限视图 | 无 | 聚合详情，不含 storage_path |
| PATCH `/api/candidates/{id}` | Admin/HR | CandidatePatch | 更新档案、version+1、审计、同步任务 |
| POST `/api/candidates/{id}/applications` | Admin/HR | `{job_id,owner_id,source,applied_at}` | 创建 candidate_jobs，重复返回 409 |
| POST `/api/candidates/{id}/delete-proposal` | Admin/HR | `{version,reason,idempotency_key}` | 总是创建审批，不直接删除 |
| POST `/api/candidates/import-resume` | Admin/HR | multipart：`file`,`job_id` | 创建 resume，提取和 AI 解析，返回预览 |
| GET `/api/resumes/{resume_id}` | Admin/HR | 无 | 解析状态与预览，不返回 storage_path |
| POST `/api/resumes/{resume_id}/retry` | Admin/HR | CSRF | failed 状态重新解析 |
| POST `/api/resumes/{resume_id}/confirm` | Admin/HR | `{corrected_data,candidate_id?,job_id}` | 创建或关联候选人和应聘关系 |

简历上传响应：

```json
{
  "resume_id": "uuid",
  "parse_status": "review_required",
  "duplicate": false,
  "existing_resume_id": null,
  "parsed_data": {
    "name": "张三",
    "phone": "138****0000",
    "email": "z***@example.com",
    "skills": ["Python", "FastAPI"],
    "education": [],
    "work_experience": [],
    "projects": [],
    "years_of_experience": 3.0
  },
  "confidence": 0.93,
  "warnings": []
}
```

重复 SHA-256 返回 200 和已有 `resume_id`，不得重复调用模型。

## 6. 面试 API

```python
class InterviewCreate(BaseModel):
    candidate_job_id: UUID
    round: Literal["screening", "first", "second", "final"]
    interview_type: Literal["phone", "online", "onsite"]
    scheduled_at: datetime
    duration_minutes: int = 60
    interviewer_id: UUID
    additional_interviewers: list[str] = []
    meeting_url: AnyHttpUrl | None = None
    location: str | None = None

class InterviewFeedback(BaseModel):
    version: int
    strengths: str
    weaknesses: str
    feedback: str
    recommendation: Literal["pass", "reject", "hold"]
```

| 方法与路径 | 权限 | 行为 |
|---|---|---|
| GET `/api/interviews` | Admin/HR 全部；Interviewer 仅本人 | 按日期、状态、岗位分页 |
| POST `/api/interviews` | Admin/HR | 创建面试和提醒；岗位关闭返回 409 |
| GET `/api/interviews/{id}` | 有对象权限 | 返回面试和受限候选人信息 |
| PATCH `/api/interviews/{id}` | Admin/HR | 仅 scheduled 可改时间/面试官，乐观锁 |
| POST `/api/interviews/{id}/cancel` | Admin/HR | 取消面试及待发送提醒 |
| POST `/api/interviews/{id}/feedback` | 负责 Interviewer/Admin/HR | 保存原始反馈、生成 AI 摘要；不直接执行高风险状态 |

`recommendation=pass` 可生成常规阶段提议；`reject/hold` 创建状态提议并按审批规则处理。

## 7. 状态与审批 API

| 方法与路径 | 权限 | 请求 | 行为 |
|---|---|---|---|
| POST `/api/applications/status-proposals` | Admin/HR/Agent Tool | StatusChangeProposal | 自动执行或创建审批 |
| GET `/api/approvals` | Admin/HR | status、request_type、owner_id、分页 | 待办/历史列表 |
| GET `/api/approvals/{id}` | Admin/有范围 HR | 无 | 返回提议、对象当前版本和历史 |
| POST `/api/approvals/{id}/approve` | Admin/有范围 HR | `{version,comment?}` | 重校验后单次执行；恢复 Graph |
| POST `/api/approvals/{id}/reject` | Admin/有范围 HR | `{version,comment}` | comment 必填；不修改目标对象 |

批准响应：

```json
{
  "approval": {"id": "uuid", "status": "approved"},
  "execution": {"action": "update_candidate_status", "target_id": "uuid"},
  "graph_resumed": true
}
```

重复批准已经 `approved` 的审批返回 200 和首次执行结果；目标版本变化时返回 409 并将审批标记为 `conflict`。

## 8. Agent API

```python
class AgentChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str                 # 1..4000
    idempotency_key: str         # 16..64
    action_response: ActionResponse | None = None
    client_timezone: str = "Asia/Shanghai"

class AgentChatResponse(BaseModel):
    conversation_id: UUID
    message: str
    data: dict | list | None
    tool_calls: list[ToolCallSummary]
    approval: ApprovalSummary | None
    status: Literal["completed", "clarification_required", "approval_required", "failed"]
    intent: IntentSummary
    clarification: ClarificationCard | None
    context: PublicContextSummary
```

| 方法与路径 | 权限 | 行为 |
|---|---|---|
| POST `/api/agent/chat` | Admin/HR；Interviewer 仅查询本人数据 | 执行 LangGraph，返回工具摘要或审批卡片 |
| GET `/api/agent/conversations` | Login | 只返回当前用户会话 |
| GET `/api/agent/conversations/{id}/messages` | 会话所有者/Admin | 分页返回展示消息，不含思维链 |
| POST `/api/agent/conversations/{id}/archive` | 会话所有者/Admin | 归档会话 |
| GET `/api/agent/conversations/{id}/memory` | 会话所有者/Admin | 返回脱敏摘要和当前实体 |
| DELETE `/api/agent/conversations/{id}/memory` | 会话所有者/Admin | 清除该会话摘要和实体上下文 |
| GET `/api/agent/preferences` | Login | 返回当前用户允许的长期偏好 |
| DELETE `/api/agent/preferences/{key}` | Login | 软删除指定偏好 |

同一用户、会话和 `idempotency_key` 的重复请求返回已有结果。

## 9. Dashboard API

| 方法与路径 | 权限 | 查询 | 响应 |
|---|---|---|---|
| GET `/api/dashboard` | Admin/HR | job_id、owner_id、date_from、date_to | 汇总全部组件 |
| GET `/api/dashboard/funnel` | Admin/HR | 同上 | 各阶段 count |
| GET `/api/dashboard/conversions` | Admin/HR | 同上 | 相邻阶段进入量与转化率 |
| GET `/api/dashboard/tasks` | Admin/HR | days=7 | 面试、next_action、审批、同步失败 |
| GET `/api/events/stream` | Login | 无 | SSE 数据变化通知，不含敏感数据 |

转化率分母为在时间范围内进入前一阶段的应聘关系数；分母为 0 时返回 `null`，不返回无穷或 0 的误导值。

## 10. 入站消息 API

```python
class DemoInboundRequest(BaseModel):
    external_event_id: str | None = None
    sender_external_id: str = "hr_demo"
    room_external_id: str = "recruitment_demo_group"
    content: str
    occurred_at: datetime | None = None
```

| 方法与路径 | 权限 | 行为 |
|---|---|---|
| POST `/api/inbound/demo` | Admin/HR | 创建事件、去重并处理；未给 event_id 时服务端生成 |
| GET `/api/inbound/events` | Admin/HR | 按状态、来源、日期分页 |
| GET `/api/inbound/events/{id}` | Admin/HR | 返回原文、提取、工具和最终状态 |
| POST `/api/inbound/events/{id}/retry` | Admin/HR | 仅 failed 可重试，复用原幂等键 |
| GET `/api/inbound/wecom` | WeCom Server | URL 验证，签名错误 403 |
| POST `/api/inbound/wecom` | WeCom Server | 验签、解密、标准化、快速返回 |

WeCom 未启用时回调返回 503 `INTEGRATION_DISABLED`；Demo 接口仍可用。

## 11. 同步与通知 API

| 方法与路径 | 权限 | 行为 |
|---|---|---|
| GET `/api/sync/jobs` | Admin/HR | 按 sink、status、entity 分页 |
| POST `/api/sync/jobs/{id}/retry` | Admin/HR | failed 且次数未超限时重置为 pending |
| GET `/api/sync/health` | Admin | 返回各 Sink enabled/healthy，不返回凭证 |
| GET `/api/notifications` | Login | 当前用户；Admin/HR 可按业务范围查询 |
| POST `/api/notifications/{id}/cancel` | Admin/HR | 仅 pending/failed 可取消 |
| POST `/api/notifications/{id}/retry` | Admin/HR | failed 且未超限可重试 |

## 12. 健康检查

| 方法与路径 | 权限 | 判断标准 |
|---|---|---|
| GET `/health/live` | Public | 进程可响应即 200 |
| GET `/health/ready` | Public | 配置合法、MySQL 可查询、迁移为 head；外部集成只报告状态 |

## 13. Agent Tool 白名单

所有 Tool：

- 输入输出使用 Pydantic；
- 不接受原始 SQL、表名或自由形式过滤表达式；
- 通过当前用户上下文执行权限校验；
- 修改类必须接收 `idempotency_key`；
- 返回内容默认脱敏；
- Tool 不能提交与 Service 不同的事务规则。

### 13.1 `search_candidates`

输入：

```json
{
  "keywords": ["Python", "FastAPI"],
  "job_id": null,
  "status": "interview_1",
  "source": null,
  "owner_id": null,
  "limit": 20
}
```

输出：`{total,items:[{candidate_id,name,masked_phone,masked_email,application_id,job_name,status,next_action_at}]}`。只读，无副作用。

### 13.2 `get_candidate_detail`

输入：`{candidate_id}`。输出按调用者角色裁剪的详情；Interviewer 必须有关联面试。

### 13.3 `create_candidate`

输入：CandidateCreate + `idempotency_key`。Admin/HR；手机号/邮箱冲突时返回匹配建议，不自动合并。

### 13.4 `parse_resume`

输入：`{resume_id}`。只允许已上传且状态可解析的记录；输出结构化预览，不自动确认入库。

### 13.5 `create_interview`

输入：InterviewCreate + `idempotency_key`。调用面试 Service，同时创建提醒和审计。

### 13.6 `record_interview_feedback`

输入：`{interview_id,version,strengths,weaknesses,feedback,recommendation,idempotency_key}`。保存原文和 AI 摘要；状态变化另走 `propose_status_change`。

### 13.7 `propose_status_change`

输入：StatusChangeProposal。输出 `{execution, application?, approval?}`；禁止跳过风险校验。

### 13.8 `create_approval_request`

输入：`{request_type,target_id,proposed_action,proposed_data,reason,confidence,target_version,idempotency_key}`。仅允许预定义动作与对应 Schema。

### 13.9 `schedule_notification`

输入：`{candidate_job_id?,interview_id?,channel,recipient,content,scheduled_at,idempotency_key}`。内容先脱敏；外部发送异步完成。

### 13.10 `get_recruitment_dashboard`

输入：`{job_id?,owner_id?,date_from?,date_to?}`。输出与 Dashboard API 相同的结构化指标；不生成 SQL。

### 13.11 `sync_recruitment_document`

输入：`{entity_type,entity_id,sink_type,idempotency_key}`。只创建同步任务，不在 Agent 请求事务内直接调用外部服务。

## 14. 接口副作用矩阵

| 操作 | 主数据 | 历史 | 审计 | 同步任务 | 审批 |
|---|---:|---:|---:|---:|---:|
| 查询 | 否 | 否 | 可选访问日志 | 否 | 否 |
| 新建候选人/应聘 | 是 | 初始阶段 | 是 | 是 | 否 |
| 常规阶段自动推进 | 是 | 是 | 是 | 是 | 否 |
| 高风险阶段提议 | 否 | 否 | 是 | 否 | 是 |
| 批准高风险动作 | 是 | 是 | 是 | 是 | 更新审批 |
| 拒绝审批 | 否 | 否 | 是 | 否 | 更新审批 |
| 面试反馈 | 是 | 否 | 是 | 是 | 视状态提议 |
| 入站无关消息 | 否 | 否 | 可选 | 否 | 否 |
| 同步重试 | 否 | 否 | 是 | 更新任务 | 否 |
