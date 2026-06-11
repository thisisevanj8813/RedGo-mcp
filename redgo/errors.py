"""RedGo 统一结构化错误（阶段4完整版）。

str(err) 就是一个 JSON 对象：{code, message, retryable, is_risk_control, suggested_action}。
MCP 把异常文本原样放进 tool 错误结果——agent 拿到的就是可解析的结构化错误，
能自主决策：retryable=true 才考虑重试；is_risk_control=true 立即停手冷却；
suggested_action 告诉它（或用户）下一步具体干什么。

错误目录：
  LOGIN_EXPIRED         未登录/登录态失效（cookie 缺失、API 业务码、登录墙）
  RISK_CONTROL          请求被平台拦截（风控类业务码、HTTP 406/461/403）
  HTTP_ERROR            网关/服务端错误
  CAPTURE_TIMEOUT       页面未在预期时间内加载出目标数据（如重复导航、页面异常）
  NOT_IMPLEMENTED       当前版本未实现的功能（如深翻分页），明确告知而非静默
  QUOTA_EXCEEDED        当日请求额度已用尽
  QUIET_HOURS           处于静默时段
  DEPLOY_HEADLESS / DEPLOY_DATACENTER_IP   运行环境检查未通过
  CDP_CONNECT_FAILED / NO_BROWSER_CONTEXT  连不上用户 Chrome
  MISSING_XSEC_TOKEN    缺 token（不可凭 note_id 凭空构造）
  NOTE_NOT_AVAILABLE    笔记数据不存在（已删除/不可见）
  INTERNAL              未归类的内部错误（兜底）
"""

from __future__ import annotations

import json


class RedGoError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        is_risk_control: bool = False,
        suggested_action: str = "",
    ):
        self.code = code
        self.message = message
        self.retryable = retryable
        self.is_risk_control = is_risk_control
        self.suggested_action = suggested_action
        super().__init__(json.dumps(self.to_dict(), ensure_ascii=False))

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "is_risk_control": self.is_risk_control,
            "suggested_action": self.suggested_action,
        }
