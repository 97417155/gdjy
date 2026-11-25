# -*- coding: utf-8 -*-
"""标准库 HTTP 适配层（零依赖运行模式）。

只做协议适配：解析请求 → 调 app/service.py → 输出 JSON / SSE / 静态资源。
业务逻辑一律不写在这里，便于与 FastAPI 版本共存（见 server/fastapi_app.py）。
"""
from __future__ import annotations

import json
import mimetypes
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from app import service
from app.config import WEB_DIR, CURRENT_PERIOD


def _ok(data):
    return 200, {"ok": True, "data": data}


def _err(msg, code=400):
    return code, {"ok": False, "message": str(msg)}


class Handler(BaseHTTPRequestHandler):
    server_version = "GDJY-AIQS/1.1"

    def log_message(self, fmt, *args):
        pass

    # ---------------- 跨域 ----------------
    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---------------- GET ----------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                code, payload = self._api_get(path, qs)
                self._json(code, payload)
            else:
                self._static(path)
        except KeyError as e:
            self._json(404, {"ok": False, "message": str(e).strip("'\"")})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"ok": False, "message": str(e)})

    def _api_get(self, path, qs):
        one = lambda k, d=None: qs.get(k, [d])[0]  # noqa: E731
        if path == "/api/health":
            return _ok({"status": "up", "server": "stdlib"})
        if path == "/api/meta":
            return _ok(service.meta())
        if path == "/api/periods":
            return _ok(service.periods())
        if path == "/api/dashboard":
            return _ok(service.dashboard_data(one("user_id"), one("start", CURRENT_PERIOD[0]),
                                              one("end", CURRENT_PERIOD[1])))
        if path == "/api/metrics":
            return _ok(service.metrics_dict())
        if path == "/api/schema":
            return _ok(service.schema())
        if path.startswith("/api/table/"):
            return _ok(service.table_detail(path.split("/")[-1]))
        if path == "/api/kpi-wide":
            return _ok(service.kpi_wide(one("period", CURRENT_PERIOD[0])))
        if path == "/api/audit":
            return _ok(service.audit(int(one("limit", "50"))))
        if path == "/api/report/list":
            return _ok(service.report_list())
        if path == "/api/report/export":
            fmt = one("fmt", "md")
            info = service.report_export(one("id"), fmt)
            return 200, {"__raw__": info["data"], "__filename__": info["filename"],
                         "__ctype__": info["ctype"], "__inline__": fmt == "html"}
        if path.startswith("/api/report/"):
            return _ok(service.report_get(path.split("/")[-1]))
        return _err("未知接口 %s" % path, 404)

    # ---------------- POST ----------------
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if path in ("/api/ask/stream", "/api/report/stream"):
                self._sse(path, body)
                return
            code, payload = self._api_post(path, body)
            self._json(code, payload)
        except KeyError as e:
            self._json(404, {"ok": False, "message": str(e).strip("'\"")})
        except ValueError as e:
            self._json(400, {"ok": False, "message": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"ok": False, "message": str(e)})

    def _api_post(self, path, body):
        if path == "/api/ask":
            return _ok(service.ask(body.get("user_id"), body.get("question", ""),
                                   body.get("session_id") or "web"))
        if path == "/api/report/build":
            return _ok(service.report_build(body.get("user_id"), body.get("start"),
                                            body.get("end")))
        if path == "/api/report/validate":
            return _ok(service.report_validate(body.get("user_id"), body.get("report_id")))
        if path == "/api/report/action":
            return _ok(service.report_action(body.get("user_id"), body.get("report_id"),
                                             body.get("action", ""), body.get("comment", "")))
        return _err("未知接口 %s" % path, 404)

    def _sse(self, path, body):
        """Server-Sent Events：阶段提示（+ SQL 逐字）+ 最终结果。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._cors_headers()
        self.end_headers()
        if path == "/api/report/stream":
            gen = service.stream_report_build(body.get("user_id"), body.get("start"),
                                              body.get("end"))
        else:
            gen = service.stream_ask(body.get("user_id"), body.get("question", ""),
                                     body.get("session_id") or "web")
        try:
            for event in gen:
                self.wfile.write(event.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------------- 输出 ----------------
    def _json(self, code, payload):
        if isinstance(payload, dict) and "__raw__" in payload:
            raw = payload["__raw__"]
            data = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", payload.get("__ctype__", "text/plain; charset=utf-8"))
            if not payload.get("__inline__"):
                self.send_header("Content-Disposition",
                                 "attachment; filename*=UTF-8''%s"
                                 % quote(payload["__filename__"]))
            self.send_header("Content-Length", str(len(data)))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(data)
            return
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path):
        """静态资源；非 /api 且未命中的路径回退到 index.html（Vue history 路由）。"""
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.exists():
            if path.startswith("/assets/"):
                self._json(404, {"ok": False, "message": "not found"})
                return
            target = WEB_DIR / "index.html"
            if not target.exists():
                self._json(404, {"ok": False, "message": "前端未构建：请在 frontend 下执行 npm run build"})
                return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(host: str = "127.0.0.1", port: int = 8848):
    httpd = ThreadingHTTPServer((host, port), Handler)
    print("=" * 66)
    print(" 广东院经营分析智能问数系统 · 标准库服务器")
    print(" 访问地址: http://%s:%d" % (host, port))
    print("=" * 66)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
