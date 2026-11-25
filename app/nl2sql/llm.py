# -*- coding: utf-8 -*-
"""大模型接入层：OpenAI 兼容协议，未配置时自动退回内置规则引擎。

设计为"可插拔"：
  * 有 Key：走真实大模型（DeepSeek / Qwen / 内网 vLLM 均可，只要兼容 /chat/completions）
  * 无 Key：走本地规则引擎（planner），保证演示环境零依赖可跑
这条设计也符合生产实践：模型永远只是链路中的一环，链路本身要能在模型不可用时降级。
"""
from __future__ import annotations

import json
import urllib.request
from typing import List, Optional

from app.config import LLM_MODE, LLM_BASE, LLM_KEY, LLM_MODEL, LLM_TIMEOUT


def available() -> bool:
    if LLM_MODE == "offline":
        return False
    return bool(LLM_KEY)


def status() -> dict:
    return {
        "mode": LLM_MODE,
        "model": LLM_MODEL if available() else "内置规则引擎（离线）",
        "online": available(),
    }


def chat(messages: List[dict], temperature: float = 0.2, max_tokens: int = 1500) -> Optional[str]:
    """调用大模型；失败一律返回 None，由上层降级，不抛异常打断主流程。"""
    if not available():
        return None
    url = LLM_BASE.rstrip("/") + "/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + LLM_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def extract_sql(text: Optional[str]) -> Optional[str]:
    """从模型回复中提取 SQL（兼容 ```sql 代码块与纯文本）。"""
    if not text:
        return None
    t = text.strip()
    if "UNSUPPORTED" in t.upper():
        return None
    if "```" in t:
        parts = t.split("```")
        for p in parts:
            body = p.strip()
            if body.lower().startswith("sql"):
                body = body[3:].strip()
            if body.upper().startswith(("SELECT", "WITH")):
                return body
    if t.upper().startswith(("SELECT", "WITH")):
        return t
    return None
