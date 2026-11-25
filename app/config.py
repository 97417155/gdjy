# -*- coding: utf-8 -*-
"""全局配置：路径、常量、可切换的 LLM 提供方。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
KB_DIR = DATA_DIR / "kb"
DB_DIR = DATA_DIR / "db"
DB_PATH = DB_DIR / "gdjy.db"
WEB_DIR = BASE_DIR / "web"

# ---- 业务时间口径 ----------------------------------------------------------
# 全库数据截至 2026-10-31；本期报告取 2026 年 10 月整月（月度经营分析）
DATA_END = "2026-10-31"
CURRENT_PERIOD = ("2026-10-01", "2026-10-31")
PREV_PERIOD = ("2026-09-01", "2026-09-30")
YEAR = 2026

# ---- 组织与权限 ------------------------------------------------------------
# 岗位 -> 可见范围：ALL=全院 / ORG=本分公司及下级 / DEPT=本部门 / PROJ=参与项目
ROLE_SCOPE = {
    "院长": "ALL",
    "副院长": "ALL",
    "分公司负责人": "ORG",
    "部门负责人": "DEPT",
    "项目经理": "PROJ",
    "设计工程师": "PROJ",
    "商务经理": "ORG",
    "财务专员": "ALL",
}
# 敏感指标（成本、利润）仅这些岗位可见，其余返回脱敏
FIN_ROLES = {"院长", "副院长", "分公司负责人", "财务专员"}
# 这些岗位只看得到脱敏后的利润/成本类指标
MASKED_KPI_CATEGORIES = {"CAT_PROFIT"}
MASK_TEXT = "***（无权限）"

# ---- LLM ----------------------------------------------------------------
# auto: 有环境变量则调用 OpenAI 兼容接口，否则使用内置规则引擎（离线可跑）
LLM_MODE = os.environ.get("GDJY_LLM_MODE", "auto").lower()
LLM_BASE = os.environ.get("GDJY_LLM_BASE", "https://api.deepseek.com/v1")
LLM_KEY = os.environ.get("GDJY_LLM_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
LLM_MODEL = os.environ.get("GDJY_LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT = int(os.environ.get("GDJY_LLM_TIMEOUT", "60"))

# ---- 报表工作流状态机 ------------------------------------------------------
WF_STATES = ["草稿", "已校验", "待审批", "已通过", "已推送"]
WF_TRANSITIONS = {
    "草稿": ["已校验", "待审批"],
    "已校验": ["待审批", "草稿"],
    "待审批": ["已通过", "草稿"],
    "已通过": ["已推送"],
    "已推送": [],
}

# ---- 只读安全守卫 ----------------------------------------------------------
FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "GRANT", "REVOKE", "MERGE", "COMMIT", "ROLLBACK",
)
