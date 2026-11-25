# -*- coding: utf-8 -*-
"""知识库检索（RAG 的本地实现）：制度、办法、口径说明。

不依赖向量库与分词库：用字符二元组 + BM25 打分，中文场景下召回效果足够，
且完全离线可跑。生产环境把 tokenize/bm25 换成 embedding + 向量检索即可，
上层的"检索 -> 拼接引用 -> 生成"结构不变。
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Dict, List, Tuple

from app.config import KB_DIR

_DOCS: List[Dict] = []
_DF: Dict[str, int] = {}
_AVG_LEN = 0.0


def _tokenize(text: str) -> List[str]:
    text = re.sub(r"\s+", "", text.lower())
    tokens = re.findall(r"[a-z0-9_]+", text)
    # 中文：字符二元组
    zh = re.findall(r"[\u4e00-\u9fa5]", text)
    for i in range(len(zh) - 1):
        tokens.append(zh[i] + zh[i + 1])
    return tokens


def _split_chunks(md: str, doc_name: str) -> List[Dict]:
    chunks = []
    parts = re.split(r"\n(?=## )", md)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.split("\n")
        title = lines[0].lstrip("# ").strip() if lines[0].startswith("#") else doc_name
        body = "\n".join(lines[1:]).strip() if lines[0].startswith("#") else part
        if len(body) < 30:
            continue
        chunks.append({"doc": doc_name, "title": title, "text": body})
    return chunks


def load(force: bool = False) -> List[Dict]:
    global _DOCS, _DF, _AVG_LEN
    if _DOCS and not force:
        return _DOCS
    _DOCS = []
    for path in sorted(Path(KB_DIR).glob("*.md")):
        md = path.read_text(encoding="utf-8")
        for c in _split_chunks(md, path.stem):
            c["tokens"] = _tokenize(c["title"] + c["text"])
            c["len"] = max(1, len(c["tokens"]))
            _DOCS.append(c)
    _DF = {}
    for d in _DOCS:
        for t in set(d["tokens"]):
            _DF[t] = _DF.get(t, 0) + 1
    _AVG_LEN = sum(d["len"] for d in _DOCS) / max(1, len(_DOCS))
    return _DOCS


def search(query: str, top_k: int = 3) -> List[Dict]:
    docs = load()
    if not docs:
        return []
    qtokens = _tokenize(query)
    n = len(docs)
    k1, b = 1.5, 0.75
    scored: List[Tuple[float, Dict]] = []
    for d in docs:
        tf: Dict[str, int] = {}
        for t in d["tokens"]:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        title_tokens = set(_tokenize(d["title"]))
        for t in set(qtokens):
            if t in title_tokens:
                score += 1.6          # 标题命中加权，制度问句更容易落到对应章节
        for t in set(qtokens):
            if t not in tf:
                continue
            idf = math.log(1 + (n - _DF.get(t, 0) + 0.5) / (_DF.get(t, 0) + 0.5))
            denom = tf[t] + k1 * (1 - b + b * d["len"] / _AVG_LEN)
            score += idf * tf[t] * (k1 + 1) / denom
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    out = []
    for s, d in scored[:top_k]:
        out.append({"doc": d["doc"], "title": d["title"], "text": d["text"], "score": round(s, 2)})
    return out


def _kpi_caliber_block(query: str) -> str:
    """若问题里点到了登记过的指标，直接给出权威口径（比检索更准）。"""
    try:
        from app import metrics as M, db
        kpi = None
        for k, meta in M.METRICS.items():
            if meta["name"] in query:
                kpi = k
                break
        if not kpi:
            return ""
        conn = db.get_conn()
        row = conn.execute("""SELECT K.KPI_NAME, K.UNIT, K.DEFINITION, K.OWNER_DEPT,
                                     C.CALIBER_NAME, C.BI_ALIGNED
                              FROM DIM_KPI K LEFT JOIN DIM_CALIBER C
                                ON C.CALIBER_ID = K.CALIBER_ID WHERE K.KPI_ID = ?""",
                           (kpi,)).fetchone()
        conn.close()
        if not row:
            return ""
        return ("**%s**（单位：%s，归口：%s）\n\n%s\n\n> 口径编号：%s%s"
                % (row["KPI_NAME"], row["UNIT"], row["OWNER_DEPT"] or "—",
                   row["DEFINITION"] or "—", row["CALIBER_NAME"] or "—",
                   "，已与 BI 平台对齐" if row["BI_ALIGNED"] else "，尚未与 BI 对齐"))
    except Exception:
        return ""


def answer(query: str, top_k: int = 3) -> Dict:
    hits = search(query, top_k)
    if not hits:
        return {"found": False, "answer": "知识库中未检索到相关规定，建议咨询归口管理部门。", "sources": []}
    body = []
    cal = _kpi_caliber_block(query)
    if cal:
        body.append(cal)
    for h in hits:
        text = h["text"].strip()
        text = re.sub(r"\n{2,}", "\n", text)
        body.append("【%s】%s" % (h["title"], text[:400]))
    sources = [{"doc": h["doc"], "title": h["title"], "score": h["score"]} for h in hits]
    return {
        "found": True,
        "answer": "根据院内制度文件：\n\n" + "\n\n".join(body),
        "sources": sources,
    }


def stats() -> Dict:
    docs = load()
    files = sorted({d["doc"] for d in docs})
    return {"chunks": len(docs), "files": len(files), "list": files}
