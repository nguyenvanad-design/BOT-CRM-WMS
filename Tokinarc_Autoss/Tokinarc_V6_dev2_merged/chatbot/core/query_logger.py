# core/query_logger.py
# TOKINARC Observability — Query Logger
# =====================================
# Log mỗi request: intent · confidence · latency · fallback · match_type
# Output: JSONL file → dễ parse, dễ aggregate
# UTF-8 NO BOM

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

log = logging.getLogger("tokinarc.query_logger")

# ─── Config ───────────────────────────────────────────────────────────────────

_LOG_DIR  = Path(os.environ.get("TOKINARC_LOG_DIR", "logs"))
_LOG_FILE = _LOG_DIR / "queries.jsonl"
_MAX_BYTES = 50 * 1024 * 1024  # 50MB rồi rotate


# ─── QueryLogger ──────────────────────────────────────────────────────────────

class QueryLogger:
    """
    Thread-safe JSONL logger cho mỗi query.

    Usage:
        logger = get_query_logger()
        logger.log(raw_pipeline_result, query="béc 350A", session_id="abc")

    Mỗi dòng JSONL:
        {
          "ts":           "2026-05-24T06:00:00Z",
          "session_id":   "abc123",
          "query":        "béc 350A",
          "intent":       "SEARCH_BY_DESC",
          "confidence":   0.821,
          "band":         "HIGH",
          "success":      true,
          "match_type":   "exact",
          "fallback":     false,
          "latency_ms":   1234.5,
          "parts_count":  8,
          "mode":         "v7_3layer"
        }
    """

    def __init__(self, log_file: Path = _LOG_FILE):
        self._file = log_file
        self._lock = Lock()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log.info(f"[QueryLogger] logging to {log_file}")

    def log(
        self,
        result: dict,
        query: str = "",
        session_id: Optional[str] = None,
    ):
        """Ghi 1 dòng JSONL từ raw pipeline result dict."""
        try:
            # Extract part codes từ bot response text
            import re
            bot_text = result.get("text", "")
            part_codes = re.findall(r'\b\d{6}\b|[A-Z]{2,}[\dA-Z\-]{4,}', bot_text)
            part_codes = list(dict.fromkeys(part_codes))[:20]  # dedup, max 20

            entry = {
                "ts":           datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "session_id":   session_id or result.get("session_id", ""),
                "query":        (query or result.get("query", ""))[:300],
                "intent":       result.get("intent", ""),
                "confidence":   round(result.get("confidence", 0.0), 3),
                "band":         result.get("confidence_band", ""),
                "success":      result.get("success", False),
                "match_type":   result.get("match_type", "none"),
                "fallback":     result.get("fallback_used", False),
                "latency_ms":   round(result.get("latency_ms", 0.0), 1),
                "parts_count":  result.get("parts_count", 0),
                "mode":         result.get("mode", ""),
                # --- Fields mới ---
                "tools_called":       result.get("tools_called", []),
                "bot_response":       bot_text[:500],  # 500 chars đầu
                "part_codes_in_resp": part_codes,
                "no_tool_called":     len(result.get("tools_called", [])) == 0 and result.get("success", False),
                "feedback":           None,  # sẽ được update qua /feedback endpoint
            }
            line = json.dumps(entry, ensure_ascii=False) + "\n"
            with self._lock:
                self._rotate_if_needed()
                with open(self._file, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception as ex:
            log.warning(f"[QueryLogger] log failed: {ex}")

    def update_feedback(
        self,
        session_id: str,
        query: str,
        rating: int,          # 1 = thumbs up, -1 = thumbs down
        comment: str = "",
    ):
        """
        Ghi feedback vào file riêng logs/feedback.jsonl.
        Không sửa queries.jsonl để tránh race condition.
        """
        try:
            feedback_file = self._file.parent / "feedback.jsonl"
            entry = {
                "ts":         datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "session_id": session_id,
                "query":      query[:300],
                "rating":     rating,   # 1 = 👍, -1 = 👎
                "comment":    comment[:500],
            }
            line = json.dumps(entry, ensure_ascii=False) + "\n"
            with self._lock:
                with open(feedback_file, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception as ex:
            log.warning(f"[QueryLogger] feedback failed: {ex}")

    def feedback_stats(self, last_n: int = 500) -> dict:
        """Aggregate feedback stats."""
        try:
            feedback_file = self._file.parent / "feedback.jsonl"
            if not feedback_file.exists():
                return {"total": 0}
            lines = feedback_file.read_text(encoding="utf-8").strip().splitlines()
            entries = [json.loads(l) for l in lines[-last_n:]]
            total     = len(entries)
            thumbs_up = sum(1 for e in entries if e.get("rating") == 1)
            thumbs_dn = sum(1 for e in entries if e.get("rating") == -1)
            # Top 10 câu bị thumbs down
            bad = [e for e in entries if e.get("rating") == -1][-10:]
            return {
                "total":       total,
                "thumbs_up":   thumbs_up,
                "thumbs_down": thumbs_dn,
                "sat_rate":    round(thumbs_up / total, 3) if total else 0,
                "recent_bad":  [{"query": e["query"], "comment": e.get("comment","")} for e in bad],
            }
        except Exception:
            return {"total": 0}

    def _rotate_if_needed(self):
        """Rotate nếu file > _MAX_BYTES."""
        try:
            if self._file.exists() and self._file.stat().st_size > _MAX_BYTES:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                rotated = self._file.with_suffix(f".{ts}.jsonl")
                self._file.rename(rotated)
                log.info(f"[QueryLogger] rotated → {rotated.name}")
        except Exception as ex:
            log.warning(f"[QueryLogger] rotate failed: {ex}")

    def tail(self, n: int = 20) -> list[dict]:
        """Đọc n dòng cuối — dùng cho debug endpoint."""
        try:
            if not self._file.exists():
                return []
            lines = self._file.read_text(encoding="utf-8").strip().splitlines()
            return [json.loads(l) for l in lines[-n:]]
        except Exception:
            return []

    def stats(self, last_n: int = 1000) -> dict:
        """
        Aggregate stats từ n dòng cuối.
        Trả về: total, success_rate, avg_latency, intent_breakdown, fallback_rate
        """
        entries = self.tail(last_n)
        if not entries:
            return {"total": 0}

        total        = len(entries)
        success      = sum(1 for e in entries if e.get("success"))
        fallbacks    = sum(1 for e in entries if e.get("fallback"))
        latencies    = [e["latency_ms"] for e in entries if e.get("latency_ms")]
        intent_count: dict[str, int] = {}
        for e in entries:
            intent_count[e.get("intent", "?")] = intent_count.get(e.get("intent", "?"), 0) + 1

        return {
            "total":         total,
            "success_rate":  round(success / total, 3),
            "fallback_rate": round(fallbacks / total, 3),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
            "p95_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 1) if latencies else 0,
            "intent_breakdown": dict(sorted(intent_count.items(), key=lambda x: -x[1])),
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[QueryLogger] = None


def get_query_logger() -> QueryLogger:
    global _instance
    if _instance is None:
        _instance = QueryLogger()
    return _instance
