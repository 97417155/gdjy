# -*- coding: utf-8 -*-
"""FastAPI 适配层（可选运行模式）。

与 app/api.py（标准库版）并列：两者都只做协议适配，业务全部在 app/service.py。
启动：python run.py --server fastapi   或   uvicorn server.fastapi_app:app --port 8848
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPS = ROOT / "_pydeps"
if DEPS.exists():                       # 离线安装的依赖目录（pip --target）
    sys.path.insert(0, str(DEPS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query           # noqa: E402
from fastapi.middleware.cors import CORSMiddleware          # noqa: E402
from fastapi.responses import (FileResponse, PlainTextResponse,  # noqa: E402
                               Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles                  # noqa: E402
from pydantic import BaseModel, Field                        # noqa: E402
from urllib.parse import quote                               # noqa: E402

from app import service                                      # noqa: E402
from app.config import CURRENT_PERIOD, WEB_DIR                # noqa: E402

app = FastAPI(title="广东院经营分析智能问数", version="1.1",
              description="报告自动生成 + 项目画像问答（FastAPI 适配层）")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ------------------------------ 请求模型 ------------------------------
class AskIn(BaseModel):
    user_id: str | None = None
    question: str = Field(min_length=1)
    session_id: str | None = None


class ReportBuildIn(BaseModel):
    user_id: str | None = None
    start: str | None = None
    end: str | None = None


class ReportIdIn(BaseModel):
    user_id: str | None = None
    report_id: str


class ReportActionIn(BaseModel):
    user_id: str | None = None
    report_id: str
    action: str
    comment: str = ""


def ok(data):
    return {"ok": True, "data": data}


# ------------------------------ 基础 ------------------------------
@app.get("/api/health")
def health():
    return ok({"status": "up", "server": "fastapi"})


@app.get("/api/meta")
def meta():
    return ok(service.meta())


@app.get("/api/periods")
def periods():
    return ok(service.periods())


@app.get("/api/dashboard")
def dashboard(user_id: str | None = None,
              start: str = CURRENT_PERIOD[0], end: str = CURRENT_PERIOD[1]):
    return ok(service.dashboard_data(user_id, start, end))


@app.get("/api/metrics")
def metrics():
    return ok(service.metrics_dict())


@app.get("/api/schema")
def schema():
    return ok(service.schema())


@app.get("/api/table/{name}")
def table_detail(name: str):
    try:
        return ok(service.table_detail(name))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'\""))


@app.get("/api/kpi-wide")
def kpi_wide(period: str = CURRENT_PERIOD[0]):
    return ok(service.kpi_wide(period))


@app.get("/api/audit")
def audit(limit: int = Query(50, ge=1, le=500)):
    return ok(service.audit(limit))


# ------------------------------ 问答 ------------------------------
@app.post("/api/ask")
def ask(body: AskIn):
    try:
        return ok(service.ask(body.user_id, body.question, body.session_id or "web"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ask/stream")
def ask_stream(body: AskIn):
    """SSE：阶段提示 + SQL 逐字 + 最终结果。"""
    return StreamingResponse(
        service.stream_ask(body.user_id, body.question, body.session_id or "web"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


# ------------------------------ 报告 ------------------------------
@app.post("/api/report/build")
def report_build(body: ReportBuildIn):
    return ok(service.report_build(body.user_id, body.start, body.end))


@app.post("/api/report/stream")
def report_stream(body: ReportBuildIn):
    """SSE：报告生成逐步推送（指标抽取 / 同比环比 / 正文 / 校验 / 落库）。"""
    return StreamingResponse(
        service.stream_report_build(body.user_id, body.start, body.end),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


@app.post("/api/report/validate")
def report_validate(body: ReportIdIn):
    return ok(service.report_validate(body.user_id, body.report_id))


@app.post("/api/report/action")
def report_action(body: ReportActionIn):
    return ok(service.report_action(body.user_id, body.report_id, body.action, body.comment))


@app.get("/api/report/list")
def report_list():
    return ok(service.report_list())


@app.get("/api/report/export")
def report_export(id: str, fmt: str = "md"):
    """导出：md / docx / pdf / html（fmt 决定格式与文件名）。"""
    info = service.report_export(id, fmt)
    headers = {}
    if fmt != "html":          # HTML 直接内联预览，其余格式下载
        headers["Content-Disposition"] = (
            "attachment; filename*=UTF-8''%s" % quote(info["filename"]))
    return Response(content=info["data"], media_type=info["ctype"], headers=headers)


@app.get("/api/report/{report_id}")
def report_get(report_id: str):
    try:
        return ok(service.report_get(report_id))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'\""))


# ------------------------------ 静态资源（Vue 构建产物） ------------------------------
if (WEB_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")


@app.get("/{full_path:path}")
def spa(full_path: str):
    """history 路由回退：非 /api 的未命中路径一律返回 index.html。"""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="未知接口 /%s" % full_path)
    target = WEB_DIR / (full_path or "index.html")
    if target.is_file():
        return FileResponse(str(target))
    index = WEB_DIR / "index.html"
    if not index.exists():
        return PlainTextResponse("前端未构建：请在 frontend 下执行 npm run build", status_code=404)
    return FileResponse(str(index))
