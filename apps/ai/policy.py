# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, Any, List
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apps.ai.intents import NLUResult, Intent, suggest_spas_from_text
from apps.utils.spa_locations import spa_locations
from apps.utils.spa_services import spa_services

VN = ZoneInfo("Asia/Ho_Chi_Minh")

@dataclass
class Rule:
    name: str
    priority: int
    condition: Callable[[NLUResult, Dict[str, Any]], bool]
    handler: Callable[[NLUResult, Dict[str, Any]], Any]


# ============================
#         HELPERS
# ============================
PROMOS = {  # demo promo
    ("Spa Serenity", "Massage đá nóng"): "giảm 20% cho thành viên GlowMeUp"
}

RELAX_SERVICE_CANDIDATES = [
    "Massage đá nóng",
    "Massage thư giãn",
]


def _now_vn():
    return datetime.now(VN)


def _save_suggestions_as_last_list(helper, env, names: List[str]):
    items = [s for s in spa_locations if s.get("name") in names]
    if not items:
        items = [{"name": n, "address": "(đang cập nhật)"} for n in names]
    helper.save_last_spa_list(env["conversation_key"], items)


def _infer_default_city():
    # Ưu tiên thành phố xuất hiện nhiều nhất trong dữ liệu spa
    from collections import Counter
    cities = []
    for spa in spa_locations:
        parts = [p.strip().lower() for p in spa.get("address", "").split(",")]
        if len(parts) >= 2:
            cities.append(parts[-1])
    common = Counter(cities).most_common(1)
    city = (common[0][0] if common else "hồ chí minh").title()
    return city


def _pick_relax_spa_and_service(city: str):
    # Chọn spa trong city có dịch vụ thuộc RELAX_SERVICE_CANDIDATES; ưu tiên Spa Serenity
    spas = []
    for spa in spa_locations:
        if city.casefold() in spa.get("address", "").casefold():
            spas.append(spa["name"])
    if not spas:
        spas = [s["name"] for s in spa_locations]
    # ưu tiên Serenity nếu có
    if "Spa Serenity" in spas:
        for svc_name in RELAX_SERVICE_CANDIDATES:
            for s in spa_services.get("Spa Serenity", []):
                if s["name"].casefold() == svc_name.casefold():
                    return "Spa Serenity", s["name"]
    # fallback: spa đầu tiên có 1 dịch vụ relax
    for sp in spas:
        for s in spa_services.get(sp, []):
            if any(s["name"].casefold() == cand.casefold() for cand in RELAX_SERVICE_CANDIDATES):
                return sp, s["name"]
    # cuối cùng: spa đầu tiên với dịch vụ đầu tiên
    sp = spas[0]
    sv = spa_services.get(sp, [{}])[0].get("name", "")
    return sp, sv


def _two_slots_for_range(start_iso: str, end_iso: str):
    start = datetime.fromisoformat(start_iso).astimezone(VN)
    end = datetime.fromisoformat(end_iso).astimezone(VN)
    # đề xuất 2 khung: 14:30 và 16:00 nếu nằm trong khoảng & sau thời điểm hiện tại
    proposals = []
    for h, m in [(14,30), (16,0)]:
        cand = start.replace(hour=h, minute=m, second=0, microsecond=0)
        if cand < start:
            cand = cand + timedelta(days=0)  # giữ nguyên ngày
        if start <= cand <= end and cand > _now_vn():
            proposals.append(cand)
    # nếu rỗng, tạo 2 slot kế tiếp mỗi 90'
    if not proposals:
        cur = max(start, _now_vn() + timedelta(minutes=30))
        proposals = [cur, cur + timedelta(minutes=90)]
    return [
        {"label": d.strftime("%d/%m/%Y %H:%M"), "iso": d.isoformat()} for d in proposals
    ]


def _format_slots_line(slots):
    # "14:30 hoặc 16:00"
    hm = [datetime.fromisoformat(s["iso"]).astimezone(VN).strftime("%H:%M") for s in slots]
    if len(hm) == 1:
        return hm[0]
    return f"{hm[0]} hoặc {hm[1]}"


# ============================
#          HANDLERS
# ============================

def _greeting(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]
    text = "Xin chào, em là Glow AI – trợ lý làm đẹp của anh. Em có thể gợi ý spa, dịch vụ và đặt lịch nhanh cho anh."
    return h.finalize_reply(text, env["conversation_key"], env["history"])


def _suggest_relax(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]
    city = env["slots"].get("city") or _infer_default_city()
    spa_name, service_name = _pick_relax_spa_and_service(city)

    # Set context để sau câu "chiều nay" có thể nhảy thẳng ra slot
    ctx = h.get_booking_context(env["user_id"]) or {}
    ctx.update({"active": True, "spa_name": spa_name, "service_name": service_name})
    h.set_booking_context(env["user_id"], ctx)

    promo = PROMOS.get((spa_name, service_name))
    promo_line = f" – {promo}." if promo else "."

    reply = (
        f"Em cảm nhận mood của anh đang cần sự thư thái. Gợi ý: Một liệu trình **{service_name}** tại **{spa_name}** gần anh{promo_line}\n"
        f"Anh muốn em kiểm tra lịch hôm nay không?"
    )
    return h.finalize_reply(reply, env["conversation_key"], env["history"])


def _city_list(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]
    city = env["slots"].get("city")
    if not city:
        return h.finalize_reply("Bạn muốn tìm spa ở **thành phố** nào ạ?", env["conversation_key"], env["history"])
    spas = h.find_spas_by_city(spa_locations, city)
    return h.reply_spa_list(city, spas, env["conversation_key"], env["history"])


def _spa_intro(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]
    spa_name = env["slots"].get("spa_name")
    if not spa_name:
        # gợi ý gần đúng
        names = [n for n,_ in suggest_spas_from_text(env["message"], limit=5, cutoff=60)]
        if names:
            _save_suggestions_as_last_list(h, env, names)
            return h.reply_choose_spa_from_last_list(env["conversation_key"], env["history"], note="từ gợi ý gần đúng")
        return h.finalize_reply("Bạn cho mình **tên spa** để giới thiệu chi tiết nhé.", env["conversation_key"], env["history"])
    return h.reply_spa_intro(spa_name, spa_locations, env["conversation_key"], env["history"])


def _list_services(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]
    spa_name = env["slots"].get("spa_name")
    if not spa_name:
        names = [n for n,_ in suggest_spas_from_text(env["message"], limit=5, cutoff=60)]
        if names:
            _save_suggestions_as_last_list(h, env, names)
            return h.reply_choose_spa_from_last_list(env["conversation_key"], env["history"], note="từ gợi ý gần đúng")
        return h.finalize_reply("Bạn muốn xem **danh sách dịch vụ** của **spa nào**?", env["conversation_key"], env["history"])
    return h.reply_service_list(spa_name, spa_services, env["conversation_key"], env["history"])


def _booking(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]; user_id = env["user_id"]; msg = env["message"]
    ctx = h.get_booking_context(user_id) or {"active": True}

    # nếu đang ở flow relax → đã có spa+service
    # override theo slots đã enrich
    slots = env.get("slots", {})
    if slots.get("spa_name"): ctx["spa_name"] = slots["spa_name"]
    if slots.get("service_name"): ctx["service_name"] = slots["service_name"]

    # 1) nếu user nêu time_range (ví dụ: chiều nay) & chưa có slot → đề xuất 2 khung giờ
    if nlu.time_range and not ctx.get("slot"):
        cand_slots = _two_slots_for_range(nlu.time_range.start_iso, nlu.time_range.end_iso)
        ctx["available_slots"] = cand_slots
        h.set_booking_context(user_id, ctx)
        line = _format_slots_line(cand_slots)
        reply = f"Có {len(cand_slots)} khung giờ khả dụng: {line}. Anh muốn em đặt luôn không?"
        return h.finalize_reply(reply, env["conversation_key"], env["history"])

    # 2) nếu user chọn giờ bằng text (16:00) hoặc số thứ tự
    pick_time = re.search(r"\b(\d{1,2}):(\d{2})\b", msg)
    if (ctx.get("available_slots") and pick_time) or (ctx.get("available_slots") and msg.strip() in {"1","2"}):
        chosen = None
        if msg.strip() in {"1","2"}:
            idx = int(msg.strip()) - 1
            if 0 <= idx < len(ctx["available_slots"]):
                chosen = ctx["available_slots"][idx]
        else:
            hm = f"{pick_time.group(1).zfill(2)}:{pick_time.group(2).zfill(2)}"
            for s in ctx["available_slots"]:
                if datetime.fromisoformat(s["iso"]).astimezone(VN).strftime("%H:%M") == hm:
                    chosen = s; break
        if chosen:
            ctx["slot"] = chosen
            h.set_booking_context(user_id, ctx)
            nlu.is_confirm = True  # chọn giờ + ngữ cảnh đặt → coi như xác nhận nhanh

    # 3) khi đã đủ thông tin & có xác nhận → chốt ngay
    if nlu.is_confirm and ctx.get("spa_name") and ctx.get("service_name") and ctx.get("slot"):
        confirmation = h.confirm_booking(ctx)
        h.add_appointment(user_id, ctx)
        h.clear_booking_context(user_id)
        # tuỳ chọn: thêm dòng QR nếu app hỗ trợ
        confirmation += "\nBạn sẽ nhận được mã QR check-in ngay trên ứng dụng."
        return h.finalize_reply(confirmation, env["conversation_key"], env["history"])

    # 4) nếu còn thiếu slot mà không có time_range → gợi ý slot chuẩn helper
    if ctx.get("spa_name") and ctx.get("service_name") and not ctx.get("slot"):
        slots2 = h.get_available_slots(ctx["spa_name"])  # dùng helper mặc định
        ctx["available_slots"] = slots2[:2]
        h.set_booking_context(user_id, ctx)
        line = _format_slots_line(ctx["available_slots"])
        return h.finalize_reply(f"Lịch gần nhất: {line}. Anh chọn khung nào?", env["conversation_key"], env["history"])

    # 5) thiếu spa/service → hỏi kèm gợi ý gần đúng
    if not ctx.get("spa_name"):
        names = [n for n,_ in suggest_spas_from_text(msg, limit=5, cutoff=60)]
        if names:
            _save_suggestions_as_last_list(h, env, names)
            return h.reply_choose_spa_from_last_list(env["conversation_key"], env["history"], note="từ gợi ý gần đúng để đặt lịch")
        return h.finalize_reply("Bạn muốn đặt tại **spa** nào?", env["conversation_key"], env["history"])
    if not ctx.get("service_name"):
        names = [s["name"] for s in spa_services.get(ctx["spa_name"], [])]
        return h.reply_choose_service_for_spa(ctx["spa_name"], names, env["conversation_key"], env["history"])

    # fallback
    return h.finalize_reply("Bạn muốn đặt **dịch vụ gì**, tại **spa nào** và **khi nào** ạ?", env["conversation_key"], env["history"])


def _service_detail(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]
    svc = env["slots"].get("service_name")
    if svc:
        for spa_name, services in spa_services.items():
            for s in services:
                if s["name"] == svc:
                    exact = {"spa_name": spa_name, "service": s}
                    return h.reply_service_detail(exact, env["conversation_key"], env["history"])
    exact = h.find_exact_service_by_name(env.get("message", ""), spa_services)
    if exact:
        return h.reply_service_detail(exact, env["conversation_key"], env["history"])
    return h.finalize_reply("Bạn cho mình **tên dịch vụ** cụ thể để giới thiệu chi tiết nhé.", env["conversation_key"], env["history"])


def _appt_lookup(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]
    tr = nlu.time_range
    if tr and tr.start_iso and tr.end_iso:
        try:
            s = datetime.fromisoformat(tr.start_iso)
            e = datetime.fromisoformat(tr.end_iso)
            title = f"📅 **Lịch hẹn ({tr.label or tr.start_iso} → {tr.end_iso}):**"
            return h.reply_my_appointments_in_range(env["user_id"], s, e, title, env["conversation_key"], env["history"])
        except Exception:
            pass
    return h.reply_my_appointments(env["user_id"], env["conversation_key"], env["history"])


def _appt_list_all(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]
    return h.reply_my_appointments(env["user_id"], env["conversation_key"], env["history"])


def _skincare(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]
    client = env["client"]
    return h.reply_with_gpt_history(client, env["history"], env["message"], env["user_id"])


def _fallback(nlu: NLUResult, env: Dict[str, Any]):
    h = env["helper"]
    client = env["client"]
    return h.reply_with_gpt_history(client, env["history"], env["message"], env["user_id"])


# ============================
#           RULES
# ============================
import re

RULES = [
    Rule("greeting",        110, lambda nlu, env: nlu.intent == Intent.GREETING, _greeting),
    Rule("booking_confirm", 100, lambda nlu, env: nlu.intent == Intent.BOOKING and nlu.is_confirm, _booking),
    Rule("booking",          95, lambda nlu, env: nlu.intent == Intent.BOOKING, _booking),
    Rule("suggest_relax",    90, lambda nlu, env: nlu.intent == Intent.SUGGEST_RELAX, _suggest_relax),
    Rule("service_detail",   80, lambda nlu, env: nlu.intent == Intent.SERVICE_DETAIL, _service_detail),
    Rule("list_services",    70, lambda nlu, env: nlu.intent == Intent.LIST_SERVICES, _list_services),
    Rule("spa_intro",        60, lambda nlu, env: nlu.intent == Intent.SPA_INTRO, _spa_intro),
    Rule("list_spas",        50, lambda nlu, env: nlu.intent == Intent.LIST_SPAS, _city_list),
    Rule("appt_lookup",      40, lambda nlu, env: nlu.intent == Intent.APPT_LOOKUP, _appt_lookup),
    Rule("appt_list_all",    30, lambda nlu, env: nlu.intent == Intent.APPT_LIST_ALL, _appt_list_all),
    Rule("skincare",         20, lambda nlu, env: nlu.intent == Intent.SKINCARE_QA, _skincare),
    Rule("fallback",          0, lambda nlu, env: True, _fallback),
]


def route(nlu: NLUResult, env: Dict[str, Any]):
    for r in sorted(RULES, key=lambda x: -x.priority):
        if r.condition(nlu, env):
            return r.handler(nlu, env)
    return _fallback(nlu, env)