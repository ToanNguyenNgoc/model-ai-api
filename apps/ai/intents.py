# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import re
import unicodedata
from enum import Enum
from typing import Optional, Literal, Dict, Any, List
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from openai import OpenAI

from apps.utils.spa_locations import spa_locations
from apps.utils.spa_services import spa_services
from apps.vector.parse_time_text import ParseTimeText

# rapidfuzz (tuỳ chọn). Nếu không có, code sẽ fallback sang difflib
try:  # pragma: no cover
    from rapidfuzz import process as rf_process, fuzz as rf_fuzz
except Exception:  # pragma: no cover
    rf_process = None
    rf_fuzz = None


# ============================
#           INTENTS
# ============================
class Intent(str, Enum):
    LIST_SPAS = "list_spas"         # Liệt kê spa theo vị trí
    SPA_INTRO = "spa_intro"         # Giới thiệu/địa chỉ một spa
    LIST_SERVICES = "list_services" # Liệt kê dịch vụ của 1 spa
    SERVICE_DETAIL = "service_detail" # Giới thiệu chi tiết một dịch vụ
    BOOKING = "booking"             # Luồng đặt lịch / nói thời gian
    APPT_LOOKUP = "appt_lookup"     # Xem lịch hẹn theo mốc thời gian
    APPT_LIST_ALL = "appt_list_all" # Liệt kê mọi lịch hẹn
    SKINCARE_QA = "skincare_qa"     # Hỏi đáp skincare chung
    SUGGEST_RELAX = "suggest_relax" # Gợi ý spa khi user nói muốn thư giãn
    GREETING = "greeting"           # Xin chào/khởi động AI
    FALLBACK = "fallback"


class TimeRange(BaseModel):
    start_iso: Optional[str] = None
    end_iso: Optional[str] = None
    label: Optional[str] = None  # ví dụ: "this_afternoon"


class NLUResult(BaseModel):
    intent: Intent
    spa_name_raw: Optional[str] = None
    service_name_raw: Optional[str] = None
    city_raw: Optional[str] = None
    datetime_raw: Optional[str] = None
    time_range: Optional[TimeRange] = None
    is_confirm: bool = False
    lang: Literal["vi", "en", "auto"] = "auto"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# ============================
#     NORMALIZE & MAPPERS
# ============================
_pt = ParseTimeText()
VN = ZoneInfo("Asia/Ho_Chi_Minh")


def _normalize(s: str) -> str:
    s = (s or "").casefold().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")
    s = re.sub(r"\s+", " ", s)
    return s


def build_city_keywords(spas):
    city_map = {}
    for spa in spas:
        parts = [p.strip().lower() for p in spa.get("address", "").split(",")]
        if len(parts) >= 2:
            city = parts[-1]
            city_map.setdefault(city, set()).add(city)
    city_map.setdefault("hồ chí minh", set()).update({
        "hồ chí minh", "ho chi minh", "tp hcm", "tp.hcm", "tp. hcm", "hcm",
        "sài gòn", "sai gon", "sg", "ho chi minh city"
    })
    city_map.setdefault("hà nội", set()).update({"hà nội", "ha noi", "hn", "ha noi city"})
    return {k: list(v) for k, v in city_map.items()}


CITY_KWS = build_city_keywords(spa_locations)
SPA_NAMES: List[str] = list(spa_services.keys())
ALIAS_STOPWORDS = {"spa", "tham", "my", "vien", "tmv"}


def map_city(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    msg = _normalize(raw)
    for city, keys in CITY_KWS.items():
        for k in keys:
            if _normalize(k) in msg:
                return city
    return None


def build_spa_alias_index(spa_names: List[str]) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    def _norm(s: str) -> str:
        return _normalize(s)
    for name in spa_names:
        norm_full = _norm(name)
        toks = [t for t in norm_full.split() if t not in ALIAS_STOPWORDS]
        last_tok = toks[-1] if toks else None
        # full & no-suffix
        alias_map[norm_full] = name
        alias_map[norm_full.replace(" spa", "").strip()] = name
        # hậu tố (Serenity, Bella...)
        if last_tok and len(last_tok) >= 3:
            alias_map[last_tok] = name
        # acronym (PMT...)
        ac = "".join(w[0] for w in re.findall(r"[A-Za-zÀ-Ỵà-ỵ]+", name))
        if len(ac) >= 2:
            alias_map[_norm(ac)] = name
    return alias_map


SPA_ALIAS_MAP = build_spa_alias_index(SPA_NAMES)


def map_spa_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    msg = _normalize(raw)
    # 1) match alias theo word-boundary
    hits = []
    for alias_norm, canonical in SPA_ALIAS_MAP.items():
        if re.search(rf"\b{re.escape(alias_norm)}\b", msg):
            hits.append((len(alias_norm), canonical))
    if hits:
        hits.sort(reverse=True)
        return hits[0][1]
    # 2) chứa nguyên tên đầy đủ
    for name in SPA_NAMES:
        if _normalize(name) in msg:
            return name
    # 3) fuzzy
    if rf_process:
        match = rf_process.extractOne(msg, SPA_NAMES, scorer=rf_fuzz.token_set_ratio)
        if match and match[1] >= 75:
            return match[0]
    else:
        from difflib import get_close_matches
        cand = get_close_matches(msg, [_normalize(s) for s in SPA_NAMES], n=1, cutoff=0.6)
        if cand:
            for s in SPA_NAMES:
                if _normalize(s) == cand[0]:
                    return s
    return None


def map_service_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    msg = _normalize(raw)
    # exact contains
    for spa, services in spa_services.items():
        for s in services:
            name_norm = _normalize(s["name"])
            if name_norm in msg:
                return s["name"]
    # token overlap >=2
    best = None
    best_score = 0
    for spa, services in spa_services.items():
        for s in services:
            name_norm = _normalize(s["name"]) 
            toks = [t for t in name_norm.split() if len(t) >= 3]
            score = sum(1 for t in toks if t in msg)
            if score > best_score:
                best, best_score = s["name"], score
    return best if best_score >= 2 else None


def parse_datetime(raw: Optional[str]):
    if not raw:
        return None
    try:
        return _pt.parse(raw)
    except Exception:
        return None


# ===== Time phrase extractor (ví dụ: "chiều nay", "sáng mai") =====

def _now_vn():
    return datetime.now(VN)


def extract_time_range_phrases(message: str) -> Optional[TimeRange]:
    msg = _normalize(message)
    now = _now_vn()
    # chiều nay: 13:00–18:00 hôm nay (nếu đã quá 18:00 thì null)
    if "chieu nay" in msg:
        start = now.replace(hour=13, minute=0, second=0, microsecond=0)
        end = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if end <= now:
            return None
        start = max(start, now)
        return TimeRange(start_iso=start.isoformat(), end_iso=end.isoformat(), label="this_afternoon")
    # sáng mai: 08:00–11:30 ngày mai
    if "sang mai" in msg:
        tomorrow = (now + timedelta(days=1))
        start = tomorrow.replace(hour=8, minute=0, second=0, microsecond=0)
        end = tomorrow.replace(hour=11, minute=30, second=0, microsecond=0)
        return TimeRange(start_iso=start.isoformat(), end_iso=end.isoformat(), label="tomorrow_morning")
    return None


# ============================
#      LLM PARSE (JSON)
# ============================
JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [i.value for i in Intent]},
        "spa_name_raw": {"type": ["string", "null"]},
        "service_name_raw": {"type": ["string", "null"]},
        "city_raw": {"type": ["string", "null"]},
        "datetime_raw": {"type": ["string", "null"]},
        "time_range": {
            "type": ["object", "null"],
            "properties": {
                "start_iso": {"type": ["string", "null"]},
                "end_iso": {"type": ["string", "null"]},
                "label": {"type": ["string", "null"]}
            }
        },
        "is_confirm": {"type": "boolean"},
        "lang": {"type": "string", "enum": ["vi", "en", "auto"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
    },
    "required": ["intent", "is_confirm", "confidence"]
}

SYS_PROMPT = (
    "Bạn là bộ trích xuất intent/slot cho trợ lý spa. "
    "Phân loại: greeting, suggest_relax, list_spas, spa_intro, list_services, service_detail, booking, appt_lookup, appt_list_all, skincare_qa, fallback. "
    "Nếu user xin gợi ý thư giãn/relax/xả stress → suggest_relax. "
    "Nếu câu có ý đặt lịch hoặc nói mốc thời gian (ví dụ 'chiều nay', 'sáng mai', '16:00') → booking. "
    "Nếu có từ ngữ xác nhận trực tiếp như 'đặt giúp/đặt luôn/book luôn/xác nhận' → is_confirm=true. "
    "Chỉ trả về JSON theo schema."
)


def parse_message_with_llm(client: OpenAI, message: str, history: list) -> NLUResult:
    msgs = [{"role": "system", "content": SYS_PROMPT}] + history + [
        {"role": "user", "content": message}
    ]
    try:
        out = client.chat.completions.create(
            model="gpt-4o",
            messages=msgs,
            response_format={"type": "json_object"},
        )
        data = json.loads(out.choices[0].message.content)
        nlu = NLUResult(**data)
    except Exception:
        # Fallback keyword đơn giản nếu LLM lỗi
        msg = _normalize(message)
        def any_in(xs):
            return any(x in msg for x in xs)
        if any_in(["xin chao", "chao", "hello", "hi", "glow ai", "glowai"]):
            nlu = NLUResult(intent=Intent.GREETING, confidence=0.4)
        elif any_in(["thu gian", "relax", "xa stress", "met", "met moi", "goi y gi", "massage thu gian"]):
            nlu = NLUResult(intent=Intent.SUGGEST_RELAX, confidence=0.4)
        elif any_in(["danh sach spa", "spa o", "spa tai", "spa gan", "spa quanh"]):
            nlu = NLUResult(intent=Intent.LIST_SPAS, confidence=0.3)
        elif any_in(["gioi thieu", "thong tin", "o dau", "tot khong"]):
            nlu = NLUResult(intent=Intent.SPA_INTRO, confidence=0.3)
        elif any_in(["danh sach dich vu", "bang gia", "cac dich vu", "dich vu cua"]):
            nlu = NLUResult(intent=Intent.LIST_SERVICES, confidence=0.3)
        elif any_in(["dat lich", "dat hen", "booking", "book", "giu cho", "dang ky lich", "chieu nay", "sang mai", ":"]):
            nlu = NLUResult(intent=Intent.BOOKING, confidence=0.4)
        elif any_in(["lich hen", "booking cua toi", "xem lich", "kiem tra lich"]):
            nlu = NLUResult(intent=Intent.APPT_LOOKUP, confidence=0.3)
        else:
            nlu = NLUResult(intent=Intent.FALLBACK, confidence=0.1)

    # Heuristic hậu xử lý: câu có cụm thời gian → gán time_range
    tr = extract_time_range_phrases(message)
    if tr and (nlu.intent in {Intent.FALLBACK, Intent.SUGGEST_RELAX, Intent.SKINCARE_QA, Intent.GREETING} or nlu.intent == Intent.BOOKING):
        nlu.intent = Intent.BOOKING
        nlu.time_range = tr

    # Heuristic: đặt nhanh → is_confirm
    quick_confirm = re.search(r"\b(dat giup|dat luon|book luon|xac nhan)\b", _normalize(message))
    if quick_confirm:
        nlu.is_confirm = True

    return nlu


# ============================
#   SUGGEST SPAS (PUBLIC API)
# ============================

def suggest_spas_from_text(text: str, limit: int = 5, cutoff: int = 60):
    """Trả về list [(spa_name, score)] gợi ý gần đúng từ câu người dùng.
    - Dùng RapidFuzz nếu có; fallback sang difflib nếu không.
    """
    msg = _normalize(text)
    if rf_process:  # pragma: no cover
        results = rf_process.extract(msg, SPA_NAMES, scorer=rf_fuzz.token_set_ratio, limit=limit)
        return [(name, int(score)) for name, score, _ in results if score >= cutoff]
    else:
        from difflib import SequenceMatcher
        scored = []
        for name in SPA_NAMES:
            score = int(100 * SequenceMatcher(None, msg, _normalize(name)).ratio())
            if score >= cutoff:
                scored.append((name, score))
        scored.sort(key=lambda x: -x[1])
        return scored[:limit]


# ============================
#        ENRICH SLOTS
# ============================

def enrich_slots(nlu: NLUResult) -> Dict[str, Any]:
    """Trả về dict slots đã chuẩn hoá: city, spa_name, service_name, dt (datetime obj hoặc None)."""
    city = map_city(nlu.city_raw)
    spa = map_spa_name(nlu.spa_name_raw)
    service = map_service_name(nlu.service_name_raw)
    dt = parse_datetime(nlu.datetime_raw)
    return {
        "city": city,
        "spa_name": spa,
        "service_name": service,
        "dt": dt,
    }


__all__ = [
    "Intent",
    "TimeRange",
    "NLUResult",
    "parse_message_with_llm",
    "enrich_slots",
    "suggest_spas_from_text",
    # mappers (tuỳ chọn export)
    "map_spa_name",
    "map_service_name",
    "map_city",
]