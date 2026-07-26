# RecruitFlow 验收矩阵

## 1. 使用说明

- 优先级：P0 为阻断提交，P1 为必须修复，P2 为可记录的非阻断缺陷。
- 自动化：`unit`、`api`、`integration`、`e2e`、`manual`。
- 每条用例保存测试日志、截图或录屏片段；不得用“开发者观察正常”代替证据。
- 真实模型测试使用 `@pytest.mark.live_llm`，默认测试不消耗模型额度。
- 真实第三方联调不属于 MVP 阻断项，但适配器配置和 Mock 必须通过。

## 2. 环境与数据库

| ID | P | 场景与操作 | 预期结果 | 自动化 |
|---|---:|---|---|---|
| ENV-001 | P0 | 使用合法 `.env` 启动 | 应用启动，ready=200 | integration |
| ENV-002 | P0 | 设置 `DB_NAME=langchain_db` 启动 | 拒绝启动且不执行 SQL | integration |
| ENV-003 | P0 | TEST_DB_NAME 与 DB_NAME 相同 | 测试启动失败 | unit |
| ENV-004 | P0 | 检查日志和异常 | 无密码、Token、API Key | integration |
| DB-001 | P0 | 空 `hr_recruitment` 执行 upgrade head | 15 张表、约束和索引正确 | integration |
| DB-002 | P0 | 测试库 downgrade base 后再次 upgrade | 成功且无残留冲突 | integration |
| DB-003 | P0 | Seed 执行两次 | 行数不重复，稳定业务键一致 | integration |
| DB-004 | P0 | 开发前后比较 `langchain_db` 快照 | 表名与各表行数完全一致 | integration |

## 3. 登录与权限

| ID | P | 场景与操作 | 预期结果 | 自动化 |
|---|---:|---|---|---|
| AUTH-001 | P0 | 三种预置账号正确登录 | 设置 HttpOnly Cookie，返回正确角色 | api |
| AUTH-002 | P0 | 错误密码连续 5 次 | 账号锁定 15 分钟 | api |
| AUTH-003 | P0 | 修改请求缺少 CSRF | 403 CSRF_FAILED，无副作用 | api |
| AUTH-004 | P0 | Interviewer 创建岗位/候选人 | 403，无审计外业务写入 | api |
| AUTH-005 | P0 | Interviewer 查看未分配面试候选人 | 404 或 403，不泄露存在性 | api |
| AUTH-006 | P1 | HR 访问系统密钥配置 | 403，响应不包含密钥 | api |
| AUTH-007 | P1 | 停用用户继续使用旧 Cookie | 401 | api |

## 4. 岗位与候选人

| ID | P | 场景与操作 | 预期结果 | 自动化 |
|---|---:|---|---|---|
| JOB-001 | P0 | 创建→开放→关闭岗位 | 状态与时间正确，审计完整 | api |
| JOB-002 | P1 | 重复 job_code | 409，无重复记录 | api |
| JOB-003 | P1 | salary_min 大于 salary_max | 400/422 | unit/api |
| JOB-004 | P0 | 向关闭岗位新增应聘关系 | 409 JOB_CLOSED | api |
| CAN-001 | P0 | 创建候选人并绑定岗位 | 候选人、应聘、初始历史和同步任务同事务提交 | integration |
| CAN-002 | P0 | 同一候选人应聘两个岗位 | 两条关系，阶段独立 | api |
| CAN-003 | P0 | 同候选人重复应聘同岗位 | 409，不重复创建 | api |
| CAN-004 | P0 | 旧 version 修改候选人 | 409 VERSION_CONFLICT | api |
| CAN-005 | P0 | 删除候选人 | 只创建审批，未设置 deleted_at | api |
| CAN-006 | P1 | 列表、Agent、面试官视图检查联系方式 | 均脱敏 | e2e |

## 5. 简历

| ID | P | 场景与操作 | 预期结果 | 自动化 |
|---|---:|---|---|---|
| RES-001 | P0 | 上传文本型 PDF | 提取文本并返回结构化预览 | integration |
| RES-002 | P0 | 上传 DOCX | 提取文本并返回结构化预览 | integration |
| RES-003 | P0 | 上传同一文件两次 | 第二次返回已有 resume，不调用模型 | integration |
| RES-004 | P0 | 扫描版/空文本 PDF | 422 UNSUPPORTED_SCANNED_DOCUMENT，不建候选人 | integration |
| RES-005 | P0 | 文件超过 10 MB | 413，未落永久文件 | api |
| RES-006 | P0 | PDF 后缀伪装可执行文件 | 415，删除临时文件 | integration |
| RES-007 | P1 | 模型返回非法 JSON | 修复一次；仍失败则记录 failed | unit |
| RES-008 | P0 | 模型超时 | 无候选人半记录，可重试 | integration |
| RES-009 | P0 | HR 修订并确认 | 保留 parsed_data 与 corrected_data，创建应聘关系 | api |
| RES-010 | P1 | 两人同名、无联系方式 | 不自动合并，要求人工选择 | unit/api |

## 6. 面试、状态与审批

| ID | P | 场景与操作 | 预期结果 | 自动化 |
|---|---:|---|---|---|
| INT-001 | P0 | 创建 48 小时后的面试 | 创建 scheduled 面试和 T-24h 通知 | api |
| INT-002 | P1 | 创建 2 小时后的面试 | 创建即时待办，不创建过去时间任务 | api |
| INT-003 | P0 | 面试官提交本人反馈 | 保存原文与独立 AI 摘要 | api |
| INT-004 | P0 | 面试官提交他人面试反馈 | 403 | api |
| INT-005 | P1 | 取消面试 | pending 通知同步取消 | integration |
| STG-001 | P0 | screening→interview_1，confidence=0.850 | 自动执行并写历史/审计/同步 | unit/api |
| STG-002 | P0 | 同路径 confidence=0.849 | 创建审批，不改阶段 | unit/api |
| STG-003 | P0 | final_interview→offer | 无条件审批 | api |
| STG-004 | P0 | 任意阶段→rejected/withdrawn | 无条件审批 | api |
| STG-005 | P0 | 非法跳转 new→interview_2 | 创建审批或返回非法跳转，不自动执行 | unit/api |
| STG-006 | P0 | 重放自动推进幂等键 | 只产生一次历史和同步任务 | integration |
| APR-001 | P0 | 批准 pending 审批 | 单次执行目标动作，状态 approved | integration |
| APR-002 | P0 | 重复批准同一审批 | 返回首次结果，不重复执行 | integration |
| APR-003 | P0 | 创建审批后目标 version 改变 | 批准返回 409，审批变 conflict | integration |
| APR-004 | P0 | 拒绝审批 | 需要 comment；目标数据不变 | api |
| APR-005 | P0 | HR 尝试恢复终态 | 403；仅 Admin 可审批恢复 | api |

## 7. Agent 与 Tool Calling

| ID | P | 场景与操作 | 预期结果 | 自动化 |
|---|---:|---|---|---|
| AGT-001 | P0 | 查询 Python、一面候选人 | 调用 search_candidates，最多 20 条且脱敏 | integration |
| AGT-002 | P0 | 要求执行原始 DELETE/UPDATE SQL | 拒绝，无数据库副作用 | unit/e2e |
| AGT-003 | P0 | 创建面试自然语言请求 | 调用 create_interview 并生成提醒 | integration |
| AGT-004 | P0 | 提议淘汰候选人 | 创建审批并 interrupt，不直接淘汰 | integration |
| AGT-005 | P0 | 批准后恢复 Graph | 从持久 Checkpoint 恢复并单次执行 | integration |
| AGT-006 | P0 | interrupt 后重启服务再批准 | 仍可恢复 | e2e |
| AGT-007 | P0 | Prompt 注入要求泄露 Key/SQL | 拒绝且日志不泄露 | unit/e2e |
| AGT-008 | P0 | 模型超时/限流 | 重试后安全失败，不修改数据 | integration |
| AGT-009 | P1 | 查看 agent_messages | 只含工具摘要，无思维链 | integration |
| AGT-010 | P0 | 同 idempotency_key 重发 chat | 返回原结果，Tool 不重复执行 | integration |

## 8. 入站消息

| ID | P | 场景与操作 | 预期结果 | 自动化 |
|---|---:|---|---|---|
| MSG-001 | P0 | 发送预置一面通过消息 | 唯一匹配并按规则推进 | e2e |
| MSG-002 | P0 | 发送淘汰消息 | 事件 pending_approval，业务阶段不变 | e2e |
| MSG-003 | P0 | 发送同名歧义消息 | 创建审批/人工确认，不猜测对象 | integration |
| MSG-004 | P0 | 发送无关闲聊 | 标记 ignored，不创建业务记录 | integration |
| MSG-005 | P0 | 重发 source+external_event_id | 返回原事件，业务行数不增加 | integration |
| MSG-006 | P0 | 处理失败后重试 | 最多 3 次且副作用幂等 | integration |
| MSG-007 | P1 | 图片/语音消息 | 标记 unsupported，不下载附件 | api |
| MSG-008 | P0 | WeCom 未配置时调用回调 | 503 INTEGRATION_DISABLED | api |
| MSG-009 | P1 | WeCom 签名错误 | 403，不落业务事件 | unit |

## 9. 同步、通知与看板

| ID | P | 场景与操作 | 预期结果 | 自动化 |
|---|---:|---|---|---|
| SYNC-001 | P0 | LocalExcel 首次 upsert | 创建固定列和候选人应聘行 | integration |
| SYNC-002 | P0 | 同一 application 再次同步 | 更新原行，不追加重复行 | integration |
| SYNC-003 | P0 | Sink 超时 | 主业务已提交，任务 failed/pending retry | integration |
| SYNC-004 | P0 | 重试三次失败 | 保留失败和错误摘要，可人工查看 | integration |
| SYNC-005 | P1 | 腾讯文档未配置 | health=disabled，不伪装成功 | unit/api |
| NOT-001 | P0 | Poller 重复扫描同通知 | 只发送一次 | integration |
| NOT-002 | P1 | 通知失败后成功重试 | sent_at 与次数正确 | integration |
| DASH-001 | P0 | 对测试夹具查询漏斗 | 各阶段数量与人工计算一致 | integration |
| DASH-002 | P0 | 转化率分母为 0 | 返回 null | unit |
| DASH-003 | P1 | 状态更新后刷新页面 | 2 秒内看到新数据 | e2e/manual |
| DASH-004 | P0 | 检查 SSE 消息 | 不包含姓名、电话、邮箱、简历 | integration |

## 10. 安全与交付

| ID | P | 场景与操作 | 预期结果 | 自动化 |
|---|---:|---|---|---|
| SEC-001 | P0 | 文件名包含 `../` | 使用内部路径，无法目录穿越 | integration |
| SEC-002 | P0 | 候选人姓名/反馈包含脚本 | 页面转义，不执行脚本 | e2e |
| SEC-003 | P0 | page_size=1000 | 截断或 422，最大 100 | api |
| SEC-004 | P0 | 搜索代码、文档和日志 | 无真实密钥、密码和真实个人数据 | manual/script |
| SEC-005 | P1 | API 触发内部异常 | 无堆栈/SQL，含 request_id | api |
| DEL-001 | P0 | 全新环境按 README 启动 | 可迁移、Seed、登录和打开 Dashboard | manual |
| DEL-002 | P0 | 连续运行演示主线两次 | 第二次不产生重复数据 | e2e/manual |
| DEL-003 | P0 | 停用真实外部适配器 | Demo 消息和 LocalExcel 全闭环可用 | e2e |
| DEL-004 | P0 | 最终比较旧库保护快照 | `langchain_db` 无变化 | integration |

## 11. 提交判定

满足以下条件才可标记 MVP 完成：

- P0 用例 100% 通过；
- P1 用例无已知失败；若确需保留，必须有不影响主线的证据和修复说明；
- Mock 模型全量测试通过，至少 5 条真实 Qwen 结构化用例通过；
- 演示主线无手工改数据库步骤；
- Docker/本地启动说明可由全新终端复现；
- 旧数据库保护检查通过。

