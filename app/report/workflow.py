# -*- coding: utf-8 -*-
"""报告审批与推送链路（模拟院内 OA / 集团经营平台）。

状态机：草稿 -> 已校验 -> 待审批 -> 已通过 -> 已推送
每次流转都写 FACT_APPROVAL，推送写 FACT_PUSH_LOG 并返回回执号，
保证"谁在什么时候把什么报告推给了谁"可审计。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from app import db
from app.config import WF_TRANSITIONS, WF_STATES
from app.report import builder, validator


def submit_validate(report_id: str, role: str = "院长") -> Dict[str, Any]:
    """执行校验并推进到"已校验"。"""
    rep = builder.get_report(report_id)
    if not rep:
        return {"ok": False, "message": "报告不存在"}
    # 用报告落库时的指标快照校验：分公司报告不该拿全院口径来核对
    rows, extra = builder.report_basis(rep)
    result = validator.validate(rep["content_md"], rows, role, extra)
    db.execute_write("UPDATE FACT_REPORT SET VALIDATE_JSON=?, STATUS=? WHERE REPORT_ID=?",
                     (json.dumps(result, ensure_ascii=False),
                      "已校验" if result["passed"] else "草稿", report_id))
    _write_approval(report_id, "系统校验", "系统",
                    "校验通过" if result["passed"] else "校验未通过",
                    "得分 %.1f（%d/%d）" % (result["score"], result["passed_count"], result["total"]))
    return {"ok": True, "validate": result, "status": "已校验" if result["passed"] else "草稿"}


def transition(report_id: str, action: str, approver: str, comment: str = "") -> Dict[str, Any]:
    """审批动作：approve / reject / push。"""
    rep = builder.get_report(report_id)
    if not rep:
        return {"ok": False, "message": "报告不存在"}
    status = rep["STATUS"]
    if action == "approve":
        target = "已通过" if status == "待审批" else (
            "待审批" if status in ("草稿", "已校验") else None)
        if target is None:
            return {"ok": False, "message": "当前状态（%s）不可审批" % status}
        db.execute_write("UPDATE FACT_REPORT SET STATUS=? WHERE REPORT_ID=?", (target, report_id))
        _write_approval(report_id, "审批", approver, "同意" if target == "已通过" else "提交审批", comment)
        return {"ok": True, "status": target}
    if action == "reject":
        db.execute_write("UPDATE FACT_REPORT SET STATUS=? WHERE REPORT_ID=?", ("草稿", report_id))
        _write_approval(report_id, "审批", approver, "退回修改", comment)
        return {"ok": True, "status": "草稿"}
    if action == "push":
        if status != "已通过":
            return {"ok": False, "message": "仅审批通过的报告可推送（当前 %s）" % status}
        return push(report_id, approver)
    return {"ok": False, "message": "未知动作"}


def push(report_id: str, operator: str = "系统") -> Dict[str, Any]:
    """推送到 OA 与集团经营平台，返回回执号。"""
    receipt = "OA%s" % datetime.now().strftime("%Y%m%d%H%M%S")
    pid = "PUSH%s" % datetime.now().strftime("%H%M%S%f")[:12]
    for channel, no in (("院内OA", receipt), ("集团经营平台", receipt.replace("OA", "JT"))):
        db.execute_write(
            "INSERT INTO FACT_PUSH_LOG (PUSH_ID, REPORT_ID, CHANNEL, RECEIPT_NO, PUSH_TIME, STATUS) "
            "VALUES (?,?,?,?,?,?)",
            (pid + channel[:2], report_id, channel, no,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "成功"))
    db.execute_write("UPDATE FACT_REPORT SET STATUS=? WHERE REPORT_ID=?", ("已推送", report_id))
    _write_approval(report_id, "推送", operator, "已推送", "回执号 %s" % receipt)
    return {"ok": True, "status": "已推送", "receipt_no": receipt,
            "channels": ["院内OA", "集团经营平台"],
            "message": "报告已推送至院内 OA 与集团经营平台，回执号 %s" % receipt}


def _write_approval(report_id: str, step: str, approver: str, action: str, comment: str) -> None:
    aid = "AP%s%03d" % (datetime.now().strftime("%Y%m%d%H%M%S"),
                        int(datetime.now().microsecond / 1000))
    db.execute_write(
        "INSERT INTO FACT_APPROVAL (APPROVAL_ID, REPORT_ID, STEP, APPROVER, ACTION, COMMENT, OP_TIME) "
        "VALUES (?,?,?,?,?,?,?)",
        (aid, report_id, step, approver, action, comment,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def timeline(report_id: str) -> Dict[str, Any]:
    rep = builder.get_report(report_id)
    if not rep:
        return {}
    return {
        "report_id": report_id,
        "status": rep["STATUS"],
        "states": WF_STATES,
        "allowed": WF_TRANSITIONS.get(rep["STATUS"], []),
        "approvals": rep["approvals"],
        "push": rep["push"],
    }
