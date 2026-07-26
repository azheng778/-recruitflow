如果你准备使用Vibe Coding，DevSpec不能只写“我要做一个招聘系统”，而要写成一份AI可以直接拆解、实现和验收的工程说明书。

核心原则是：

> 每个功能都要说明输入、处理逻辑、输出、异常情况和验收标准。

## 一、DevSpec推荐结构

### 1. 项目概述

说明项目解决什么问题。

```
项目名称：AI Recruitment Copilot

目标：
构建一个招聘一体化平台，帮助HR完成简历解析、候选人管理、面试记录、自然语言查询、人工审核和招聘数据可视化。

技术栈：
- Backend: FastAPI + Python
- Database: SQLite / PostgreSQL
- ORM: SQLAlchemy
- AI: LangChain + LangGraph
- Frontend: React / Vue
- Authentication: JWT
```

### 2. 项目范围

明确“做什么”和“不做什么”。

#### 本期必须完成

```
- 简历上传
- 简历AI解析
- 候选人自动入库
- 候选人列表和详情
- Agent自然语言查询
- 面试记录
- Human-in-the-loop审批
- 候选人状态流转
- 招聘数据看板
- 面试提醒任务
```

#### 本期不做

```
- 暂不接入普通微信
- 暂不接入真实企业微信双向聊天
- 暂不实现复杂权限体系
- 暂不实现自动化简历爬取
- 暂不实现薪资审批和Offer签署
```

这一部分非常重要，可以防止Vibe Coding不断扩展需求。

## 二、用户角色和核心流程

### 用户角色

```
HR：
- 上传简历
- 查询候选人
- 创建面试
- 确认AI建议
- 修改候选人状态

面试官：
- 查看分配给自己的候选人
- 填写面试反馈

管理员：
- 管理用户、岗位和系统配置
```

### 核心流程

```
上传简历
→ 提取文本
→ AI结构化解析
→ 创建候选人
→ 绑定岗位
→ HR查询候选人
→ 创建面试
→ 记录面试反馈
→ AI生成面试总结
→ 创建人工审批
→ HR确认
→ 更新候选人状态
→ 更新看板数据
```

建议给每一个流程标记状态和失败处理。

## 三、数据库设计

DevSpec中应该直接写出表结构，而不是只写表名。

例如：

```
Table: candidates

字段：
- id: UUID, primary key
- name: string, required
- phone: string, nullable
- email: string, nullable
- resume_text: text, nullable
- current_status: enum, default="new"
- created_at: datetime
- updated_at: datetime

状态：
new / screening / first_interview / second_interview /
offer / hired / rejected / withdrawn
```

每张表都写：

- 字段
- 类型
- 是否必填
- 默认值
- 唯一约束
- 外键关系
- 状态枚举

重点写清楚：

```
AI不允许直接修改候选人最终录用状态。
AI只能创建approval_requests。
HR批准后，系统才更新candidates.current_status。
```

## 四、API接口设计

每个接口至少写清楚：

- 请求方法
- URL
- 请求参数
- 返回结构
- 错误状态
- 权限要求

示例：

```
POST /api/candidates/import-resume

用途：
上传简历并触发AI解析。

请求：
multipart/form-data
- file: PDF/DOCX

返回：
{
  "candidate_id": "uuid",
  "parse_status": "completed",
  "candidate": {
    "name": "张三",
    "skills": ["Python", "FastAPI"],
    "years_of_experience": 3
  }
}

错误：
400：文件格式不支持
413：文件过大
422：简历解析失败
```

Agent相关接口：

```
POST /api/agent/chat

请求：
{
  "conversation_id": "uuid",
  "message": "找出最近两周通过一面的Python候选人"
}

返回：
{
  "message": "共找到3名候选人",
  "data": [...],
  "tool_used": "search_candidates"
}
```

## 五、Agent和Tool Calling设计

这是你项目中最需要写清楚的部分。

### Agent职责

```
Agent负责：
- 理解HR意图
- 选择工具
- 组织查询结果
- 生成总结
- 发起审批请求

Agent不负责：
- 直接执行任意SQL
- 直接删除候选人
- 直接淘汰候选人
- 绕过人工确认修改关键状态
```

### 工具清单

```
search_candidates
get_candidate_detail
create_candidate
parse_resume
create_interview
record_interview_feedback
summarize_communication
create_approval_request
get_recruitment_dashboard
schedule_notification
```

每个Tool都要写输入、输出和权限。

例如：

```
Tool: search_candidates

输入：
{
  "keywords": ["Python", "FastAPI"],
  "status": "first_interview",
  "limit": 20
}

输出：
{
  "total": 3,
  "items": [...]
}

限制：
- 只允许SELECT查询
- 不允许接收原始SQL
- 默认最多返回20条
- 手机号和邮箱默认脱敏
```

### LangGraph节点建议

```
START
  ↓
classify_intent
  ↓
retrieve_context
  ↓
select_tool
  ↓
execute_tool
  ↓
human_approval? ── yes → wait_for_approval
  ↓ no
format_response
  ↓
END
```

关键节点：

```
classify_intent：判断查询、创建、修改还是总结
select_tool：选择业务工具
execute_tool：执行工具
wait_for_approval：等待HR确认
format_response：生成最终回复
```

## 六、Human-in-the-loop规则

必须在DevSpec中明确哪些操作需要人工确认。

### 不需要确认

```
- 查询候选人
- 查看面试记录
- 生成候选人总结
- 生成招聘数据统计
- 解析简历
```

### 必须确认

```
- 淘汰候选人
- 标记面试通过
- 修改候选人核心状态
- 发送正式Offer
- 删除候选人
- 批量修改候选人
```

审批流程：

```
Agent提出建议
→ 创建approval_request
→ 前端显示待确认卡片
→ HR点击批准或拒绝
→ 执行真实数据库修改
→ 写入audit_logs
```

## 七、前端页面说明

不要只写“做一个好看的后台”，而要具体描述页面。

### 页面清单

```
1. Dashboard
2. CandidateList
3. CandidateDetail
4. ResumeImport
5. InterviewManagement
6. ApprovalCenter
7. AgentChat
8. Settings
```

例如Agent聊天页面：

```
页面要求：
- 左侧显示历史会话
- 中间显示消息列表
- 支持快捷问题
- 查询结果使用表格展示
- 修改类操作显示审批卡片
- 显示调用的业务工具名称
- 显示加载和错误状态
```

## 八、验收标准

每个功能必须写成可以判断“完成或未完成”的标准。

例如简历上传：

```
验收标准：
1. 支持PDF和DOCX文件；
2. 上传后能够提取文本；
3. AI能够解析姓名、邮箱、手机号、技能和工作经历；
4. 解析结果可以人工修改；
5. 点击保存后候选人进入数据库；
6. 重复上传相同简历时给出重复提醒；
7. 解析失败时展示明确错误信息。
```

Agent查询：

```
验收标准：
1. 支持自然语言查询候选人；
2. 能根据姓名、技能、岗位和状态进行组合筛选；
3. 只能调用白名单工具；
4. 查询结果最多返回20条；
5. 查询不到数据时返回明确提示；
6. 不允许执行DELETE或任意UPDATE。
```

## 九、开发约束

这一部分可以直接约束Vibe Coding生成代码的方式。

```
代码要求：
- 使用分层结构：router / service / repository / model
- API返回统一使用Pydantic Schema
- 所有数据库操作使用SQLAlchemy
- 不在Router中直接写复杂业务逻辑
- 所有Agent工具必须独立封装
- 所有关键修改写入audit_logs
- 不允许硬编码API Key
- 使用.env管理环境变量
- 每完成一个模块必须补充测试
- 不得修改未涉及的已有功能
```

## 十、建议的项目目录

```
project/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── routers/
│   │   ├── services/
│   │   ├── repositories/
│   │   ├── agent/
│   │   │   ├── graph.py
│   │   │   ├── state.py
│   │   │   ├── tools.py
│   │   │   └── prompts.py
│   │   └── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
├── docs/
│   ├── devspec.md
│   ├── api.md
│   └── database.md
├── docker-compose.yml
└── README.md
```

## 十一、最适合你的DevSpec写法

建议你把DevSpec拆成三层：

```
01-product-spec.md
产品目标、用户、业务流程、范围

02-technical-spec.md
架构、数据库、API、Agent、权限、安全

03-implementation-plan.md
开发顺序、任务拆分、验收标准、测试要求
```

Vibe Coding时，不要一次性让AI生成整个项目，建议按这个顺序：

```
第一步：生成项目骨架和数据库模型
第二步：实现简历上传与解析
第三步：实现候选人和面试管理
第四步：实现Agent工具
第五步：实现LangGraph流程
第六步：实现Human-in-the-loop
第七步：实现看板
第八步：统一测试和修复
```

最关键的一句话是：

> DevSpec要让另一个开发者或AI在不询问你业务细节的情况下，能够按照文档完成开发，并通过文档中的验收标准验证结果。