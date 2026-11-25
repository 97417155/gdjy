#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键启动：初始化数据 -> 构建指标宽表 -> 启动 Web 服务。

用法:
    python run.py                 # 默认 http://127.0.0.1:8848
    python run.py --port 9000     # 指定端口
    python run.py --reset         # 强制重建演示数据
    python run.py --init-only     # 只初始化，不启动服务
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEPS = ROOT / "_pydeps"
if DEPS.exists():                      # 离线安装的 FastAPI / uvicorn
    sys.path.insert(0, str(DEPS))

from app.config import DB_PATH, CURRENT_PERIOD


def bootstrap(reset: bool = False) -> None:
    from app import seed, db, metrics, permission

    need = reset or not DB_PATH.exists()
    if need:
        print("[1/4] 生成演示数据（29 张表，确定性随机）…")
        t0 = time.time()
        seed.main()
        print("      完成，用时 %.1fs" % (time.time() - t0))
    else:
        print("[1/4] 演示数据已存在，跳过（--reset 可重建）")

    print("[2/4] 加载演示账号与权限范围…")
    users = permission.init_users()
    for u in users:
        print("      %s %s（%s，%s）" % (u["user_id"], u["name"], u["role"], u["scope_type"]))

    print("[3/4] 构建指标宽表（28 指标 × 分公司 × 项目等级）…")
    t0 = time.time()
    n = metrics.build_wide(CURRENT_PERIOD[0], CURRENT_PERIOD[1])
    print("      完成，%d 行，用时 %.1fs" % (n, time.time() - t0))

    print("[4/4] 校验数据库…")
    conn = db.get_conn()
    tables = db.list_tables(conn)
    conn.close()
    print("      表数量 %d，指标 %d 个" % (len(tables), len(metrics.KPI_ORDER)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="广东院经营分析智能问数系统")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8848)
    ap.add_argument("--reset", action="store_true", help="重建演示数据")
    ap.add_argument("--init-only", action="store_true", help="只初始化不启动")
    ap.add_argument("--server", default="auto", choices=["auto", "fastapi", "stdlib"],
                    help="HTTP 服务器：auto 优先 FastAPI，缺失则用标准库")
    args = ap.parse_args(argv)

    bootstrap(reset=args.reset)
    if args.init_only:
        print("初始化完成。启动服务请执行：python run.py")
        return 0

    mode = args.server
    if mode == "auto":
        try:
            import fastapi  # noqa: F401
            import uvicorn  # noqa: F401
            mode = "fastapi"
        except ImportError:
            mode = "stdlib"

    if mode == "fastapi":
        import uvicorn
        from server.fastapi_app import app as fastapi_app
        print("=" * 66)
        print(" 广东院经营分析智能问数系统 · FastAPI")
        print(" 访问地址: http://%s:%d   接口文档: http://%s:%d/docs" % (args.host, args.port, args.host, args.port))
        print("=" * 66)
        uvicorn.run(fastapi_app, host=args.host, port=args.port, log_level="warning")
    else:
        from app.api import serve
        serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
