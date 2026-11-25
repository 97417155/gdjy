#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端自检：不依赖任何第三方测试框架，直接 python tests/test_smoke.py。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, permission, metrics as M
from app.nl2sql import lexicon as L, planner, router
from app.report import builder, validator, workflow

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  -> " + str(detail)) if detail and not cond else ""))


def main():
    print("== 1. 数据库 ==")
    conn = db.get_conn()
    tables = db.list_tables(conn)
    conn.close()
    check("表数量 ≥ 25", len(tables) >= 25, len(tables))

    print("== 2. 指标引擎（28 项）==")
    ctx = M.period_ctx("2026-10-01", "2026-10-31")
    bad = []
    for k in M.KPI_ORDER:
        try:
            v = M.metric_value(k, ctx)
            if v is None:
                bad.append(k)
        except Exception as e:
            bad.append("%s:%s" % (k, e))
    check("全部指标可计算", not bad, bad)

    print("== 3. Oracle 11g 方言 ==")
    from app import oracle_compat
    sql_mysql = "SELECT center_name FROM DIM_PROJECT LIMIT 5"
    issues = oracle_compat.lint(sql_mysql)
    check("能识别 MySQL 方言", any("LIMIT" in i["message"] for i in issues), issues)
    fixed, logs = oracle_compat.rewrite(sql_mysql)
    check("能自动改写为 ROWNUM", "ROWNUM" in fixed, fixed)

    print("== 4. 意图路由与问答 ==")
    user = permission.get_user("U001")
    cases = [
        ("2026年10月新签合同额是多少", "data"),
        ("各分公司10月新签合同额排名", "data"),
        ("近6个月营业收入趋势", "data"),
        ("哪些项目进度滞后", "data"),
        ("两金压降有什么要求", "kb"),
    ]
    for q, expect in cases:
        r = router.ask(q, user, "smoke")
        check("意图[%s] %s" % (expect, q[:18]), r["intent"] == expect, r["intent"])
        check("有回答 %s" % q[:12], bool(r.get("answer")))

    print("== 5. 权限隔离 ==")
    p1 = permission.get_user("U001")   # 院长
    p2 = permission.get_user("U005")   # 设计工程师
    n1 = len(permission.visible_projects(p1))
    n2 = len(permission.visible_projects(p2))
    check("院长可见项目多于工程师", n1 > n2, (n1, n2))
    r1 = router.ask("2026年10月新签合同额是多少", p1, "s1")
    r2 = router.ask("2026年10月新签合同额是多少", p2, "s2")
    check("工程师口径小于院长（行级隔离）",
          float(r2["rows"][0]["VAL"]) < float(r1["rows"][0]["VAL"]),
          (r2["rows"][0]["VAL"], r1["rows"][0]["VAL"]))
    rm = router.ask("毛利率是多少", p2, "s3")
    check("非财务岗利润指标脱敏", "***" in rm["answer"], rm["answer"][:60])

    print("== 6. 知识库 ==")
    a = kb.answer("新签合同额的口径")
    check("知识库命中口径文档", a["found"] and a["sources"], a["sources"])

    print("== 7. 报告生成与校验 ==")
    prev = builder.prev_period("2026-10-01", "2026-10-31")
    rep = builder.build("2026-10-01", "2026-10-31", prev[0], prev[1], builder="自检")
    check("报告含七章", all(c in rep["content_md"] for c in validator.REQUIRED_CHAPTERS))
    tables = rep["content_md"].count("\n| ---")
    check("报告图文混排（≥10 张数据表）", tables >= 10, tables)
    rows, extra = builder.report_basis(builder.get_report(rep["report_id"]))
    v = validator.validate(rep["content_md"], rows, "院长", extra)
    check("兜底校验通过", v["passed"], [i["message"] for i in v["items"] if not i["ok"]])

    print("== 7.1 生成轨迹与导出 ==")
    steps = rep["trace"]["steps"]
    check("生成轨迹含 5 个步骤", [x["name"] for x in steps] ==
          ["metrics", "compare", "compose", "guard", "save"], [x["name"] for x in steps])
    check("轨迹带耗时", all(isinstance(x["ms"], int) for x in steps))
    from app.report import export as report_export
    caps = report_export.capabilities()
    if caps["docx"]:
        data, name, ctype = report_export.export(rep["content_md"], rep["title"], "docx")
        check("导出 Word 非空", len(data) > 10000 and name.endswith(".docx"), (len(data), name))
    if caps["pdf"]:
        try:
            data, name, ctype = report_export.export(rep["content_md"], rep["title"], "pdf")
            check("导出 PDF 非空", data[:4] == b"%PDF" and len(data) > 20000, len(data))
        except RuntimeError as e:
            # Linux CI 上可能没装中文字体，此时导出会明确报错，属预期行为
            print("  [SKIP] PDF 导出：%s" % e)
    html, _, _ = report_export.export(rep["content_md"], rep["title"], "html")
    check("导出 HTML 含表格与分页样式", b"<table>" in html and b"page-break-before" in html)

    print("== 8. 审批推送链路 ==")
    workflow.submit_validate(rep["report_id"])
    workflow.transition(rep["report_id"], "approve", "陈建国", "提交审批")
    s1 = workflow.transition(rep["report_id"], "approve", "陈建国", "同意")
    s2 = workflow.transition(rep["report_id"], "push", "陈建国")
    check("审批状态推进", s1["ok"], s1)
    check("推送返回回执号", s2["ok"] and s2.get("receipt_no"), s2)

    print("== 9. 报告范围隔离与脱敏 ==")
    full = builder.build("2026-10-01", "2026-10-31", prev[0], prev[1], scope_label="全院")
    scoped = builder.build("2026-10-01", "2026-10-31", prev[0], prev[1],
                           filters=[("ORG", "=", "O103")], scope_label="新能源分公司")
    v_full = next(r["value"] for r in full["metrics"] if r["kpi_id"] == "HS_NEW_AMT")
    v_scope = next(r["value"] for r in scoped["metrics"] if r["kpi_id"] == "HS_NEW_AMT")
    check("分公司口径小于全院", v_scope < v_full, (v_scope, v_full))
    check("报告抬头标注范围", "新能源分公司" in scoped["title"], scoped["title"])
    masked_rep = builder.build("2026-10-01", "2026-10-31", prev[0], prev[1],
                               filters=[("ORG", "=", "O103")], scope_label="新能源分公司",
                               mask_profit=True)
    check("非财务岗报告不含利润指标",
          all(m["category"] != "CAT_PROFIT" for m in masked_rep["metrics"]))
    check("非财务岗报告利润章脱敏", "脱敏" in masked_rep["content_md"])

    print("== 10. 问答增强 ==")
    r = router.ask("营业收入按分公司拆分占比", user, "s4")
    cols = r.get("columns") or []
    check("占比问题返回占比列", any("占比" in c for c in cols), cols)
    r2 = router.ask("各分公司10月新签合同额排名", user, "s5")
    check("回答附带后续追问", bool(r2.get("related")), r2.get("related"))
    r3 = router.ask("今天天气不错", user, "s6")
    check("非业务问题走引导而非报错", r3["intent"] == "chat", r3["intent"])

    print("== 11. 清理自检产生的报告 ==")
    conn = db.get_conn()
    ids = [r["REPORT_ID"] for r in conn.execute(
        "SELECT REPORT_ID FROM FACT_REPORT WHERE BUILDER IN ('自检', '系统')")]
    for rid in ids:
        conn.execute("DELETE FROM FACT_APPROVAL WHERE REPORT_ID = ?", (rid,))
        conn.execute("DELETE FROM FACT_PUSH_LOG WHERE REPORT_ID = ?", (rid,))
        conn.execute("DELETE FROM FACT_REPORT WHERE REPORT_ID = ?", (rid,))
    conn.commit()
    conn.close()
    check("自检报告已清理", True)

    print("\n结果：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：", FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
