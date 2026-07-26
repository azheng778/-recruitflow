# RecruitFlow 数据库规格

## 1. 数据库边界

- MySQL 版本：8.0.x。
- 字符集：`utf8mb4`，排序规则：`utf8mb4_0900_ai_ci`。
- 业务数据库：`hr_recruitment`。
- 自动测试数据库：`hr_recruitment_test`。
- Alembic 只允许管理上述两个数据库。
- 如果数据库名为 `langchain_db`，迁移、测试、Seed 和应用启动必须立即失败。

所有时间以 UTC 写入 `DATETIME(6)`，API 和页面负责时区转换。主业务实体 UUID 使用 `CHAR(36)`；事件、消息、历史和审计使用 `BIGINT UNSIGNED AUTO_INCREMENT`。

## 2. 通用约定

### 2.1 通用字段

- `created_at`：创建时间，必填，默认数据库当前 UTC 时间。
- `updated_at`：最后更新时间，必填，由 ORM/数据库更新。
- `version`：乐观锁整数，从 1 开始，每次业务修改加 1。
- JSON 字段的结构必须由 Pydantic Schema 校验，不能写入任意不可识别对象。
- 业务枚举用 `VARCHAR` 保存、应用层 Enum 校验，避免 MySQL ENUM 迁移困难。

### 2.2 删除规则

- `candidates` 使用 `deleted_at` 软删除。
- 其他业务历史、审计、审批、消息和同步记录不提供删除 API。
- 岗位用 `status=closed` 关闭，不物理删除。
- 用户用 `is_active=false` 停用，不物理删除。

### 2.3 外键规则

- 主业务父记录被引用时默认 `ON DELETE RESTRICT`。
- 可选操作者用户停用不影响历史；历史表仍保留其 ID。
- 候选人软删除不会触发级联删除。

## 3. 表结构

### 3.1 `users`

预置账号与角色信息。

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | CHAR(36) | 必填 | PK，UUID |
| username | VARCHAR(50) | 必填 | UK，登录名，转小写保存 |
| display_name | VARCHAR(80) | 必填 | 页面显示名 |
| email | VARCHAR(255) | 可空 | UK，转小写；仅 Admin 可查看完整值 |
| phone | VARCHAR(32) | 可空 | 手机号，默认脱敏展示 |
| password_hash | VARCHAR(255) | 必填 | bcrypt 哈希 |
| role | VARCHAR(20) | 必填 | `admin/hr/interviewer` |
| department | VARCHAR(100) | 可空 | 所属部门 |
| is_active | BOOLEAN | `true` | 停用后不能登录 |
| failed_login_count | SMALLINT | `0` | 成功登录后归零 |
| locked_until | DATETIME(6) | 可空 | 登录锁定截止时间 |
| last_login_at | DATETIME(6) | 可空 | 最近成功登录 |
| created_at | DATETIME(6) | 必填 | 创建时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |

索引：`uk_users_username`、`uk_users_email`、`ix_users_role_active(role,is_active)`。

### 3.2 `jobs`

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | CHAR(36) | 必填 | PK |
| job_code | VARCHAR(40) | 必填 | UK，如 `BE-2026-001` |
| job_name | VARCHAR(120) | 必填 | 岗位名称 |
| department | VARCHAR(100) | 必填 | 部门 |
| description | TEXT | 必填 | 岗位描述 |
| requirements | TEXT | 必填 | 任职要求 |
| location | VARCHAR(120) | 可空 | 工作地点 |
| salary_min | DECIMAL(12,2) | 可空 | 非负且不大于 salary_max |
| salary_max | DECIMAL(12,2) | 可空 | 非负 |
| headcount | INT UNSIGNED | `1` | 招聘人数，必须大于 0 |
| owner_id | CHAR(36) | 必填 | FK → users.id，HR/Admin |
| status | VARCHAR(20) | `draft` | `draft/open/closed` |
| opened_at | DATETIME(6) | 可空 | 首次开放时间 |
| closed_at | DATETIME(6) | 可空 | 关闭时间 |
| created_at | DATETIME(6) | 必填 | 创建时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |
| version | INT UNSIGNED | `1` | 乐观锁 |

索引：`uk_jobs_job_code`、`ix_jobs_status_owner(status,owner_id)`、`ix_jobs_department(department)`。

### 3.3 `candidates`

候选人基础档案，不保存招聘阶段。

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | CHAR(36) | 必填 | PK |
| name | VARCHAR(100) | 必填 | 姓名 |
| phone | VARCHAR(32) | 可空 | 原始标准化手机号 |
| email | VARCHAR(255) | 可空 | 转小写保存 |
| city | VARCHAR(100) | 可空 | 所在城市 |
| source | VARCHAR(40) | `manual` | `manual/resume/wecom/referral/job_board/other` |
| current_company | VARCHAR(150) | 可空 | 当前/最近公司 |
| years_of_experience | DECIMAL(4,1) | 可空 | 0～60 |
| skills | JSON | `[]` | 字符串数组 |
| education | JSON | `[]` | 结构化教育经历 |
| work_experience | JSON | `[]` | 结构化工作经历 |
| projects | JSON | `[]` | 结构化项目经历 |
| summary | TEXT | 可空 | AI 摘要或人工摘要 |
| created_by | CHAR(36) | 必填 | FK → users.id |
| created_at | DATETIME(6) | 必填 | 创建时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |
| deleted_at | DATETIME(6) | 可空 | 软删除时间 |
| version | INT UNSIGNED | `1` | 乐观锁 |

唯一性：手机号、邮箱存在时分别使用唯一索引；MySQL 允许多个 NULL。自动合并时要求手机号或邮箱精确命中，不以姓名唯一。

索引：`uk_candidates_phone`、`uk_candidates_email`、`ix_candidates_name(name)`、`ix_candidates_source_deleted(source,deleted_at)`。

### 3.4 `candidate_jobs`

候选人与岗位的应聘关系，是招聘阶段唯一可信来源。

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | CHAR(36) | 必填 | PK |
| candidate_id | CHAR(36) | 必填 | FK → candidates.id |
| job_id | CHAR(36) | 必填 | FK → jobs.id |
| owner_id | CHAR(36) | 必填 | FK → users.id，负责 HR |
| source | VARCHAR(40) | 必填 | 应聘渠道 |
| status | VARCHAR(30) | `new` | 招聘阶段枚举 |
| match_score | DECIMAL(5,2) | 可空 | 0～100，只作参考 |
| applied_at | DATETIME(6) | 必填 | 应聘时间 |
| stage_entered_at | DATETIME(6) | 必填 | 进入当前阶段时间 |
| next_action | VARCHAR(255) | 可空 | 下一步动作摘要 |
| next_action_at | DATETIME(6) | 可空 | 待办时间 |
| rejection_reason | TEXT | 可空 | 仅 rejected 时允许 |
| created_at | DATETIME(6) | 必填 | 创建时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |
| version | INT UNSIGNED | `1` | 乐观锁 |

唯一约束：`uk_candidate_jobs_candidate_job(candidate_id,job_id)`。MVP 不支持同一候选人对同一岗位重复申请；重新开启原关系须 Admin 审批。

索引：`ix_candidate_jobs_job_status(job_id,status)`、`ix_candidate_jobs_owner_next(owner_id,next_action_at)`、`ix_candidate_jobs_stage_time(status,stage_entered_at)`。

### 3.5 `resumes`

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | CHAR(36) | 必填 | PK |
| candidate_id | CHAR(36) | 可空 | FK → candidates.id，确认入库后关联 |
| uploaded_by | CHAR(36) | 必填 | FK → users.id |
| original_file_name | VARCHAR(255) | 必填 | 仅展示，不作路径 |
| storage_path | VARCHAR(500) | 必填 | 服务端受控相对路径 |
| file_type | VARCHAR(10) | 必填 | `pdf/docx` |
| file_sha256 | CHAR(64) | 必填 | UK，小写十六进制 |
| file_size | BIGINT UNSIGNED | 必填 | 不超过配置上限 |
| raw_text | LONGTEXT | 可空 | 原始提取文本 |
| parsed_data | JSON | 可空 | AI 原始结构化结果 |
| corrected_data | JSON | 可空 | HR 确认结果 |
| parse_status | VARCHAR(30) | `uploaded` | `uploaded/extracting/parsing/review_required/completed/failed/unsupported` |
| parser_model | VARCHAR(100) | 可空 | 模型名或 `rule` |
| parser_error_code | VARCHAR(80) | 可空 | 稳定错误码 |
| parser_error_message | VARCHAR(500) | 可空 | 脱敏错误摘要 |
| created_at | DATETIME(6) | 必填 | 创建时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |

索引：`uk_resumes_sha256`、`ix_resumes_candidate(candidate_id)`、`ix_resumes_status_created(parse_status,created_at)`。

### 3.6 `interviews`

MVP 每场面试指定一名系统内负责面试官；其他人员以名称数组记录，不获得系统权限。

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | CHAR(36) | 必填 | PK |
| candidate_job_id | CHAR(36) | 必填 | FK → candidate_jobs.id |
| round | VARCHAR(20) | 必填 | `screening/first/second/final` |
| interview_type | VARCHAR(20) | 必填 | `phone/online/onsite` |
| scheduled_at | DATETIME(6) | 必填 | 面试开始时间 |
| duration_minutes | SMALLINT UNSIGNED | `60` | 15～480 |
| interviewer_id | CHAR(36) | 必填 | FK → users.id，role=interviewer/hr/admin |
| additional_interviewers | JSON | `[]` | 仅保存显示名称 |
| meeting_url | VARCHAR(500) | 可空 | online 时使用 |
| location | VARCHAR(255) | 可空 | onsite 时使用 |
| status | VARCHAR(20) | `scheduled` | `scheduled/completed/cancelled/no_show` |
| strengths | TEXT | 可空 | 人工原始反馈 |
| weaknesses | TEXT | 可空 | 人工原始反馈 |
| feedback | TEXT | 可空 | 人工原始反馈 |
| ai_summary | TEXT | 可空 | AI 摘要，不覆盖原文 |
| recommendation | VARCHAR(20) | `pending` | `pending/pass/reject/hold` |
| feedback_submitted_at | DATETIME(6) | 可空 | 首次提交时间 |
| created_by | CHAR(36) | 必填 | FK → users.id |
| created_at | DATETIME(6) | 必填 | 创建时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |
| version | INT UNSIGNED | `1` | 乐观锁 |

索引：`ix_interviews_candidate_job(candidate_job_id,scheduled_at)`、`ix_interviews_interviewer_time(interviewer_id,scheduled_at)`、`ix_interviews_status_time(status,scheduled_at)`。

### 3.7 `candidate_status_history`

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | BIGINT UNSIGNED | 必填 | PK，自增 |
| candidate_job_id | CHAR(36) | 必填 | FK → candidate_jobs.id |
| from_status | VARCHAR(30) | 可空 | 创建应聘关系时为空 |
| to_status | VARCHAR(30) | 必填 | 目标阶段 |
| reason | VARCHAR(500) | 可空 | 业务原因 |
| confidence | DECIMAL(4,3) | 可空 | 0～1 |
| operator_type | VARCHAR(20) | 必填 | `human/agent/system` |
| operator_id | CHAR(36) | 可空 | 人工操作时 FK → users.id |
| approval_request_id | CHAR(36) | 可空 | FK → approval_requests.id |
| inbound_event_id | BIGINT UNSIGNED | 可空 | FK → inbound_events.id |
| request_id | CHAR(36) | 必填 | 关联日志 |
| created_at | DATETIME(6) | 必填 | 创建时间 |

索引：`ix_status_history_application_time(candidate_job_id,created_at)`、`ix_status_history_request(request_id)`。

### 3.8 `communications`

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | BIGINT UNSIGNED | 必填 | PK，自增 |
| candidate_id | CHAR(36) | 必填 | FK → candidates.id |
| candidate_job_id | CHAR(36) | 可空 | FK → candidate_jobs.id |
| inbound_event_id | BIGINT UNSIGNED | 可空 | FK → inbound_events.id |
| channel | VARCHAR(20) | 必填 | `web/wecom/email/phone/other` |
| direction | VARCHAR(20) | 必填 | `inbound/outbound/internal` |
| content | TEXT | 可空 | MVP 可保存文本，展示时脱敏 |
| summary | TEXT | 可空 | AI/人工摘要 |
| intent | VARCHAR(80) | 可空 | 沟通意图 |
| next_action | VARCHAR(255) | 可空 | 下一步建议 |
| operator_id | CHAR(36) | 可空 | FK → users.id |
| occurred_at | DATETIME(6) | 必填 | 实际发生时间 |
| created_at | DATETIME(6) | 必填 | 入库时间 |

索引：`ix_communications_candidate_time(candidate_id,occurred_at)`、`ix_communications_application(candidate_job_id)`。

### 3.9 `notifications`

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | CHAR(36) | 必填 | PK |
| candidate_job_id | CHAR(36) | 可空 | FK → candidate_jobs.id |
| interview_id | CHAR(36) | 可空 | FK → interviews.id |
| channel | VARCHAR(20) | 必填 | `in_app/wecom` |
| recipient_type | VARCHAR(20) | 必填 | `user/webhook` |
| recipient | VARCHAR(255) | 必填 | 用户 ID 或配置引用，不存 Webhook 密钥 |
| content | TEXT | 必填 | 已脱敏通知内容 |
| scheduled_at | DATETIME(6) | 必填 | 计划发送时间 |
| sent_at | DATETIME(6) | 可空 | 成功发送时间 |
| status | VARCHAR(20) | `pending` | `pending/sending/sent/failed/cancelled` |
| retry_count | SMALLINT UNSIGNED | `0` | 最大 3 |
| next_retry_at | DATETIME(6) | 可空 | 下次重试 |
| error_code | VARCHAR(80) | 可空 | 错误码 |
| error_message | VARCHAR(500) | 可空 | 脱敏摘要 |
| created_at | DATETIME(6) | 必填 | 创建时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |

索引：`ix_notifications_due(status,scheduled_at,next_retry_at)`、`ix_notifications_interview(interview_id)`。

### 3.10 `audit_logs`

只追加，不修改。

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | BIGINT UNSIGNED | 必填 | PK，自增 |
| request_id | CHAR(36) | 必填 | 请求链路 ID |
| user_id | CHAR(36) | 可空 | FK → users.id |
| actor_type | VARCHAR(20) | 必填 | `human/agent/system` |
| action | VARCHAR(80) | 必填 | 稳定动作名 |
| target_type | VARCHAR(50) | 必填 | 业务对象类型 |
| target_id | VARCHAR(64) | 必填 | 对象 ID |
| before_data | JSON | 可空 | 修改前脱敏摘要 |
| after_data | JSON | 可空 | 修改后脱敏摘要 |
| source | VARCHAR(30) | 必填 | `web/agent/demo/wecom/worker` |
| ip_address | VARCHAR(45) | 可空 | 客户端 IP |
| created_at | DATETIME(6) | 必填 | 创建时间 |

索引：`ix_audit_target(target_type,target_id,created_at)`、`ix_audit_user_time(user_id,created_at)`、`ix_audit_request(request_id)`。

### 3.11 `agent_conversations`

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | CHAR(36) | 必填 | PK，同时作为 LangGraph thread_id |
| user_id | CHAR(36) | 必填 | FK → users.id |
| title | VARCHAR(255) | 必填 | 首条消息摘要 |
| status | VARCHAR(20) | `active` | `active/archived` |
| summary | TEXT | 可空 | 脱敏的增量会话摘要，最多约 1500 字符 |
| context_snapshot | JSON | 可空 | 当前业务实体和待处理澄清动作，不保存候选人联系方式 |
| summary_through_message_id | BIGINT | 可空 | 已纳入摘要的最后消息 ID |
| memory_version | INT | `1` | 记忆变更版本 |
| prompt_version | VARCHAR(40) | 可空 | 最近使用的 Agent Prompt 版本 |
| created_at | DATETIME(6) | 必填 | 创建时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |

索引：`ix_agent_conversations_user_time(user_id,updated_at)`。

### 3.12 `agent_messages`

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | BIGINT UNSIGNED | 必填 | PK，自增 |
| conversation_id | CHAR(36) | 必填 | FK → agent_conversations.id |
| role | VARCHAR(20) | 必填 | `user/assistant/tool/system` |
| content | LONGTEXT | 可空 | 展示内容；不得保存思维链 |
| tool_name | VARCHAR(80) | 可空 | 白名单 Tool 名 |
| tool_input | JSON | 可空 | 脱敏参数 |
| tool_output | JSON | 可空 | 截断、脱敏结果 |
| status | VARCHAR(30) | `completed` | `completed/clarification_required/approval_required/failed` |
| request_id | CHAR(36) | 必填 | 请求链路 ID |
| created_at | DATETIME(6) | 必填 | 创建时间 |

索引：`ix_agent_messages_conversation_time(conversation_id,created_at)`、`ix_agent_messages_request(request_id)`。

### 3.12.1 `agent_user_preferences`

保存用户明确要求长期记住的非敏感默认设置。`(user_id,preference_key)` 唯一；仅允许时区、面试时长、面试方式、提醒提前量和通知渠道。删除通过 `status=deleted` 实现。

### 3.12.2 `agent_tool_runs`

按请求和步骤记录工具名、脱敏输入/输出、风险等级、审批 ID、耗时、错误码、模型和 Prompt 版本。`idempotency_key` 唯一，是多步工具执行和审批恢复的审计事实来源。

### 3.13 `approval_requests`

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | CHAR(36) | 必填 | PK |
| candidate_job_id | CHAR(36) | 可空 | FK → candidate_jobs.id |
| candidate_id | CHAR(36) | 可空 | 软删除等候选人级动作使用 |
| interview_id | CHAR(36) | 可空 | FK → interviews.id |
| request_type | VARCHAR(40) | 必填 | `status_change/delete_candidate/bulk_update/reopen_terminal/other` |
| proposed_action | VARCHAR(80) | 必填 | 待执行 Service 动作名 |
| proposed_data | JSON | 必填 | 通过专用 Schema 校验 |
| reason | VARCHAR(500) | 必填 | 风险或歧义原因 |
| confidence | DECIMAL(4,3) | 可空 | AI 置信度 |
| target_version | INT UNSIGNED | 必填 | 创建审批时的对象版本 |
| idempotency_key | CHAR(64) | 必填 | UK |
| status | VARCHAR(20) | `pending` | `pending/approved/rejected/conflict/cancelled` |
| requested_by_type | VARCHAR(20) | 必填 | `human/agent/system` |
| requested_by | CHAR(36) | 可空 | FK → users.id |
| decided_by | CHAR(36) | 可空 | FK → users.id |
| decision_comment | VARCHAR(500) | 可空 | 拒绝时必填 |
| decided_at | DATETIME(6) | 可空 | 决策时间 |
| graph_thread_id | CHAR(36) | 可空 | 对应 Agent 会话 |
| graph_checkpoint_ns | VARCHAR(255) | 可空 | Checkpoint 命名空间 |
| created_at | DATETIME(6) | 必填 | 创建时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |
| version | INT UNSIGNED | `1` | 乐观锁 |

目标约束：`candidate_job_id/candidate_id/interview_id` 至少一个非空，由 Service 校验。

索引：`uk_approval_idempotency`、`ix_approvals_status_created(status,created_at)`、`ix_approvals_application(candidate_job_id)`。

### 3.14 `inbound_events`

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | BIGINT UNSIGNED | 必填 | PK，自增 |
| source | VARCHAR(20) | 必填 | `demo/wecom` |
| external_event_id | VARCHAR(128) | 必填 | 来源内唯一 ID |
| sender_external_id | VARCHAR(128) | 可空 | 外部发送者 |
| room_external_id | VARCHAR(128) | 可空 | 外部会话/群 ID |
| message_type | VARCHAR(20) | 必填 | MVP 支持 `text` |
| content | TEXT | 可空 | 文本消息 |
| occurred_at | DATETIME(6) | 必填 | 外部发生时间 |
| raw_payload | JSON | 可空 | 脱敏原始载荷 |
| extracted_data | JSON | 可空 | AI 结构化结果 |
| relevance | VARCHAR(20) | `unknown` | `unknown/relevant/irrelevant` |
| confidence | DECIMAL(4,3) | 可空 | 0～1 |
| processing_status | VARCHAR(30) | `received` | `received/processing/ignored/pending_approval/completed/failed/unsupported` |
| approval_request_id | CHAR(36) | 可空 | FK → approval_requests.id |
| error_code | VARCHAR(80) | 可空 | 处理错误码 |
| error_message | VARCHAR(500) | 可空 | 脱敏错误摘要 |
| retry_count | SMALLINT UNSIGNED | `0` | 最大 3 |
| processed_at | DATETIME(6) | 可空 | 完成时间 |
| created_at | DATETIME(6) | 必填 | 入库时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |

唯一约束：`uk_inbound_source_event(source,external_event_id)`。

索引：`ix_inbound_status_created(processing_status,created_at)`、`ix_inbound_room_time(room_external_id,occurred_at)`。

### 3.15 `document_sync_jobs`

| 字段 | 类型 | 必填/默认 | 约束与说明 |
|---|---|---|---|
| id | BIGINT UNSIGNED | 必填 | PK，自增 |
| sink_type | VARCHAR(30) | 必填 | `local_excel/tencent_docs` |
| entity_type | VARCHAR(40) | 必填 | `candidate/application/interview/event` |
| entity_id | VARCHAR(64) | 必填 | 业务实体 ID |
| operation | VARCHAR(20) | 必填 | `upsert/append` |
| payload | JSON | 必填 | 版本化同步数据 |
| payload_version | SMALLINT UNSIGNED | `1` | Payload Schema 版本 |
| idempotency_key | CHAR(64) | 必填 | UK |
| status | VARCHAR(20) | `pending` | `pending/running/succeeded/failed/cancelled` |
| retry_count | SMALLINT UNSIGNED | `0` | 最大 3 |
| next_retry_at | DATETIME(6) | 可空 | 下次重试 |
| external_record_id | VARCHAR(255) | 可空 | 外部行/记录 ID |
| error_code | VARCHAR(80) | 可空 | 错误码 |
| error_message | VARCHAR(500) | 可空 | 脱敏摘要 |
| last_attempt_at | DATETIME(6) | 可空 | 最近执行时间 |
| completed_at | DATETIME(6) | 可空 | 成功时间 |
| created_at | DATETIME(6) | 必填 | 创建时间 |
| updated_at | DATETIME(6) | 必填 | 更新时间 |

索引：`uk_sync_idempotency`、`ix_sync_due(status,next_retry_at,created_at)`、`ix_sync_entity(entity_type,entity_id)`。

## 4. 招聘阶段枚举与状态迁移

阶段：

```text
new
screening
interview_1
interview_2
final_interview
on_hold
offer
hired
rejected
withdrawn
```

| 当前阶段 | 可直接提议的目标 | 是否可自动执行 |
|---|---|---|
| new | screening, on_hold, rejected, withdrawn | 仅 screening |
| screening | interview_1, on_hold, rejected, withdrawn | 仅 interview_1 |
| interview_1 | interview_2, final_interview, on_hold, rejected, withdrawn | interview_2/final_interview |
| interview_2 | final_interview, offer, on_hold, rejected, withdrawn | 仅 final_interview |
| final_interview | offer, on_hold, rejected, withdrawn | 否 |
| on_hold | new～final_interview 中明确指定阶段, rejected, withdrawn | 否 |
| offer | hired, rejected, withdrawn | 否 |
| hired/rejected/withdrawn | Admin 审批后恢复到明确活跃阶段 | 否 |

即使表中标记“可自动”，仍需满足置信度、唯一匹配、权限、岗位开放和非批量条件。

## 5. ER 关系

```text
users ──< jobs
users ──< candidate_jobs
users ──< interviews
users ──< agent_conversations ──< agent_messages

candidates ──< resumes
candidates ──< candidate_jobs >── jobs
candidate_jobs ──< interviews
candidate_jobs ──< candidate_status_history
candidate_jobs ──< communications
candidate_jobs ──< approval_requests
candidate_jobs ──< notifications

inbound_events ──< communications
inbound_events ── approval_requests
approval_requests ──< candidate_status_history

business entities ──< document_sync_jobs
all important mutations ──< audit_logs
```

## 6. 初始数据

仅在 `APP_ENV=development|test` 时允许 Seed：

- 账号：`admin_demo`、`hr_demo`、`interviewer_demo`。
- 密码从 `DEMO_PASSWORD` 读取；未提供时仅开发环境使用文档化演示密码，生产环境必须拒绝 Seed。
- 至少 3 个开放岗位、1 个关闭岗位。
- 至少 12 名虚构候选人，覆盖所有主要阶段和 3 种来源。
- 至少 6 场面试、3 条提醒、2 条待审批和 2 条同步任务。
- 所有手机号使用保留的虚构格式，邮箱使用 `example.com`。

Seed 必须可重复执行且不重复插入，使用稳定业务键或固定 UUID。

## 7. 迁移与保护检查

首版 Alembic 迁移必须：

1. 创建全部 15 张业务表、约束和索引。
2. 分步处理 `approval_requests`、`inbound_events`、`candidate_status_history` 的相互引用外键。
3. 在全新数据库上可升级到 head。
4. 可降级到 base，仅用于空测试数据库。
5. 执行前断言当前数据库名为 `hr_recruitment` 或 `hr_recruitment_test`。

保护性回归测试应在执行前后记录 `langchain_db` 的表名和各表行数；任何变化均判定失败。
