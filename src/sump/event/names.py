"""事件名常量（事件广场统一命名，避免魔法字符串散落）"""


class SleepEvents:
    """睡眠生理事件。"""

    ENTER = "sleep.enter"
    DEEPEN = "sleep.deepen"
    WAKE = "sleep.wake"
    CONSOLIDATE_START = "sleep.consolidate.start"
    CONSOLIDATE_DONE = "sleep.consolidate.done"
    CONSOLIDATE_INTERRUPTED = "sleep.consolidate.interrupted"


class AgentEvents:
    """Agent 生命周期事件。"""

    MESSAGE_RECEIVED = "agent.message.received"  # 收到用户消息
    REPLY = "agent.reply"                        # 回复完成（session_id + content）
    TOOL_CALL = "agent.tool_call"                # 工具调用（name + args）
    TOOL_RESULT = "agent.tool_result"            # 工具结果（content）
    SESSION_SWITCHED = "agent.session.switched"  # 切换会话
    APPROVAL_PENDING = "agent.approval.pending"  # 审批挂起（call_id/session_id/command/summary/danger）
    APPROVAL_EXPIRED = "agent.approval.expired"  # 审批超时自动拒绝（call_id/session_id）
