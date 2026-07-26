"""前端展示标签。

这里仅把数据库/API 的稳定枚举映射为中文，不改变任何持久化值或接口字段。
"""

UI_LABELS = {
    # 角色
    "admin": "系统管理员",
    "hr": "招聘专员",
    "interviewer": "面试官",
    # 招聘阶段
    "new": "新候选人",
    "screening": "简历筛选",
    "interview_1": "一面",
    "interview_2": "二面",
    "final_interview": "终面",
    "on_hold": "暂缓",
    "offer": "录用意向",
    "hired": "已入职",
    "rejected": "已淘汰",
    "withdrawn": "已退出",
    # 候选人来源
    "manual": "人工录入",
    "resume": "简历导入",
    "referral": "内部推荐",
    "job_board": "招聘网站",
    "agent": "AI 助手",
    # 面试轮次、方式、状态和建议
    "first": "一面",
    "second": "二面",
    "final": "终面",
    "phone": "电话面试",
    "online": "线上面试",
    "onsite": "现场面试",
    "scheduled": "待进行",
    "completed": "已完成",
    "cancelled": "已取消",
    "pending": "待处理",
    "pass": "建议通过",
    "reject": "建议淘汰",
    "hold": "建议暂缓",
    # 审批、消息和同步
    "approved": "已批准",
    "conflict": "数据冲突",
    "received": "已接收",
    "processing": "处理中",
    "pending_approval": "等待审批",
    "irrelevant": "非招聘消息",
    "failed": "处理失败",
    "succeeded": "同步成功",
    "update_candidate_status": "更新候选人阶段",
    "soft_delete_candidate": "删除候选人",
    # Agent 工具
    "search_candidates": "查询候选人",
    "get_candidate_detail": "查看候选人详情",
    "create_candidate": "创建候选人",
    "parse_resume": "解析简历",
    "create_interview": "安排面试",
    "record_interview_feedback": "记录面试反馈",
    "propose_status_change": "提议阶段变更",
    "create_approval_request": "创建审批",
    "schedule_notification": "安排提醒",
    "get_recruitment_dashboard": "查询招聘看板",
    "sync_recruitment_document": "同步招聘文档",
}


def zh_label(value: object) -> str:
    if value is None:
        return "—"
    text = str(value)
    return UI_LABELS.get(text, text)
