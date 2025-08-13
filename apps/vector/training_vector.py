# -*- coding: utf-8 -*-
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import get_close_matches

from apps.controllers._base_controller import BaseController
from apps.extensions import cache
from apps.utils.spa_locations import spa_locations
from apps.utils.spa_services import spa_services
from openai import OpenAI
from apps.vector.parse_time_text import ParseTimeText


class TrainingVector(BaseController):
    def __init__(self):
        self.dt_parser = ParseTimeText()

    # ===== Storage / common =====
    def finalize_reply(self, reply, conversation_key, history):
        reply_text = "\n".join(reply) if isinstance(reply, list) else reply
        history.append({"role": "assistant", "content": reply_text})
        cache.set(conversation_key, history, timeout=86400)
        return self.json_response(reply_text)

    def get_booking_context(self, user_id):
        return cache.get(f"booking:{user_id}") or {"active": False}

    def set_booking_context(self, user_id, ctx):
        cache.set(f"booking:{user_id}", ctx, timeout=1800)  # 30 phút

    def clear_booking_context(self, user_id):
        cache.delete(f"booking:{user_id}")

    # ===== Normalize / utils =====
    def _normalize(self, s: str) -> str:
        s = (s or "").casefold().strip()
        s = unicodedata.normalize("NFD", s)
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
        def fold_char(ch: str) -> str:
            if ch.isascii():
                return ch
            name = unicodedata.name(ch, "")
            if name.startswith("LATIN") and " LETTER " in name and " WITH " in name:
                base = name.split(" LETTER ", 1)[1].split(" WITH ", 1)[0]
                for c in base:
                    if c.isalpha():
                        return c.lower()
            if ch in ("đ", "Đ"):
                return "d"
            return ch
        s = "".join(fold_char(ch) for ch in s)
        s = re.sub(r"\s+", " ", s)
        return s

    # ===== City detection =====
    def extract_city_keywords(self, spas):
        city_map = {}
        for spa in spas:
            parts = [p.strip().lower() for p in spa["address"].split(",")]
            if len(parts) >= 2:
                city = parts[-1]
                city_map.setdefault(city, set()).add(city)
        city_map.setdefault("hồ chí minh", set()).update({
            "hồ chí minh", "ho chi minh", "tp hcm", "tp.hcm", "tp. hcm", "hcm",
            "sài gòn", "sai gon", "sg", "ho chi minh city"
        })
        city_map.setdefault("hà nội", set()).update({"hà nội", "ha noi", "hn", "ha noi city"})
        return {k: list(v) for k, v in city_map.items()}

    def extract_city_from_message(self, message, city_keywords):
        msg_norm = self._normalize(message)
        for city, keys in city_keywords.items():
            for k in keys:
                if self._normalize(k) in msg_norm:
                    return city
        return None

    # ===== Spa / Service detection =====
    def detect_spa_in_message(self, message, spa_names):
        msg_norm = self._normalize(message)
        for name in spa_names:
            name_norm = self._normalize(name)
            if name_norm in msg_norm:
                return name
            if f"spa {name_norm}" in msg_norm or f"{name_norm} spa" in msg_norm:
                return name
        matches = get_close_matches(msg_norm, [self._normalize(s) for s in spa_names], n=1, cutoff=0.5)
        if matches:
            return next((s for s in spa_names if self._normalize(s) == matches[0]), None)
        return None

    def find_exact_service_by_name(self, message, spa_services_dict):
        msg = self._normalize(message)
        for spa_name, services in spa_services_dict.items():
            for s in services:
                if self._normalize(s["name"]) in msg:
                    return {"spa_name": spa_name, "service": s}
        return None

    # ===== Intents =====
    def is_request_for_spa_list(self, message):
        msg = self._normalize(message)
        keys = ["tim spa o", "spa o", "danh sach spa", "spa gan", "spa quanh", "spa khu vuc", "spa tai"]
        return any(k in msg for k in keys)

    def is_request_for_spa_intro(self, message, spa_name):
        msg = message.lower(); name = spa_name.lower()
        if msg.strip() == name:
            return True
        patterns = [
            fr"giới thiệu.*{re.escape(name)}", fr"{re.escape(name)}.*là gì",
            fr"thông tin.*{re.escape(name)}", fr"{re.escape(name)}.*ở đâu",
            fr"{re.escape(name)}.*tốt.*không", fr"{re.escape(name)}.*giới thiệu",
        ]
        return any(re.search(p, msg) for p in patterns)

    def is_additional_booking(self, message: str) -> bool:
        """Nhận diện 'đặt hẹn thêm' để reset context cũ trước khi vào flow mới."""
        msg = self._normalize(message)
        keys = ["dat hen them", "dat them", "dat lich them", "them mot lich", "them lich"]
        return any(k in msg for k in keys)

    def is_booking_request(self, message):
        msg = self._normalize(message)
        keywords = [
            "dat lich", "dat hen", "booking", "book", "dat ngay",
            "muon hen", "muon dat", "hen lich", "dat lich hen",
            "dat slot", "giu cho", "giup minh dat", "dang ky lich",
            # coi 'đặt thêm' cũng là booking
            "dat hen them", "dat them", "dat lich them", "them mot lich", "them lich"
        ]
        return any(k in msg for k in keywords)

    def is_request_for_service_list(self, message):
        if self.is_booking_request(message):
            return False
        msg = self._normalize(message)
        keys = [
            "danh sach dich vu", "danh sách dịch vụ", "bang gia", "bảng giá",
            "cac dich vu", "các dịch vụ", "co gi", "có gì", "gom nhung gi", "gồm những gì",
            "dich vu cua", "dịch vụ của"
        ]
        return any(k in msg for k in keys)

    def is_referring_prev_service(self, message: str) -> bool:
        msg = message.lower()
        pats = [r"dịch vụ này", r"dịch vụ đó", r"dịch vụ trên", r"dịch vụ vừa rồi", r"dịch vụ vừa nêu", r"dịch vụ vừa xong"]
        return any(re.search(p, msg) for p in pats)

    def infer_service_from_history(self, history):
        for h in reversed(history):
            content = h.get("content", "").lower()
            for spa_name, services in spa_services.items():
                for s in services:
                    if s["name"].lower() in content:
                        return {"spa_name": spa_name, "service_name": s["name"]}
        return None

    # ===== Last list / focus =====
    def save_last_spa_list(self, conversation_key, spas):
        items = [{"name": s["name"], "address": s["address"]} for s in spas]
        cache.set(f"{conversation_key}:last_spa_list", items, timeout=1800)

    def get_last_spa_list(self, conversation_key):
        return cache.get(f"{conversation_key}:last_spa_list") or []

    def reply_choose_spa_from_last_list(self, conversation_key, history, note=None):
        spa_list = self.get_last_spa_list(conversation_key)
        if not spa_list:
            return self.finalize_reply("Bạn cho mình xin **tên spa** muốn xem dịch vụ nhé.", conversation_key, history)
        lines = []
        header = "Bạn muốn xem dịch vụ của **spa nào** dưới đây:"
        if note:
            header += f" ({note})"
        lines.append(header)
        for i, item in enumerate(spa_list, 1):
            lines.append(f"{i}. **{item['name']}** — {item['address']}")
        lines.append("Vui lòng trả lời **số thứ tự** hoặc **tên spa**.")
        return self.finalize_reply("\n".join(lines), conversation_key, history)

    def resolve_spa_selection_from_message(self, message, spa_list):
        msg = message.strip().lower()
        m = re.match(r"^\s*(\d{1,2})\s*$", msg)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(spa_list):
                return spa_list[idx]["name"]
        for item in spa_list:
            if item["name"].lower() in msg:
                return item["name"]
        return None

    def resolve_service_selection_from_message(self, message, candidates):
        msg = self._normalize(message)
        m = re.match(r"^\s*(\d{1,2})\s*$", msg)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
        norm_cands = [self._normalize(c) for c in candidates]
        for i, nc in enumerate(norm_cands):
            if nc in msg:
                return candidates[i]
        best_i, best_score = -1, 0
        for i, nc in enumerate(norm_cands):
            toks = [t for t in nc.split() if len(t) >= 2]
            score = sum(1 for t in toks if t in msg)
            if score > best_score:
                best_score, best_i = score, i
        if best_score > 0:
            return candidates[best_i]
        match = get_close_matches(msg, norm_cands, n=1, cutoff=0.6)
        if match:
            i = norm_cands.index(match[0])
            return candidates[i]
        return None

    # ===== Finders =====
    def find_spas_by_city(self, spas, city):
        city_norm = self._normalize(city)
        results = []
        for spa in spas:
            text_norm = self._normalize(
                f"{spa.get('name','')} {spa.get('address','')} {spa.get('description','')}"
            )
            addr_norm = self._normalize(spa.get('address',''))
            if city_norm in addr_norm or city_norm in text_norm:
                results.append(spa)
        return results

    def get_spas_by_service_name(self, service_name):
        target = self._normalize(service_name)
        spas = []
        for spa in spa_locations:
            for s in spa_services.get(spa["name"], []):
                if self._normalize(s["name"]) == target:
                    spas.append(spa)
                    break
        return spas

    # ===== Replies =====
    def reply_spa_list(self, city, matched_spas, conversation_key, history):
        if not matched_spas:
            return self.finalize_reply(f"Hiện chưa tìm thấy spa nào tại **{city.title()}**.", conversation_key, history)
        self.save_last_spa_list(conversation_key, matched_spas)
        reply = [f"📍 Các spa tại **{city.title()}**:"]
        for spa in matched_spas:
            reply.append(f"- **{spa['name']}** — {spa['address']}")
            if spa.get("description"):
                reply.append(f"  {spa['description']}")
        reply.append("\nBạn có thể trả lời **số thứ tự** hoặc **tên spa** để xem *danh sách dịch vụ* của spa đó.")
        return self.finalize_reply("\n".join(reply), conversation_key, history)

    def reply_spa_intro(self, spa_name, spas, conversation_key, history):
        info = next((s for s in spas if s["name"] == spa_name), None)
        if info:
            reply = f"📍 **{spa_name}** — {info['address']}\n\n{info.get('description','') or 'Hiện chưa có mô tả chi tiết.'}"
            return self.finalize_reply(reply, conversation_key, history)
        return self.finalize_reply(f"Chưa có thông tin chi tiết về **{spa_name}**.", conversation_key, history)

    def reply_service_list(self, spa_name, services_dict, conversation_key, history):
        services = services_dict.get(spa_name, [])
        if not services:
            return self.finalize_reply(f"Hiện **{spa_name}** chưa cập nhật dịch vụ.", conversation_key, history)
        cache.set(f"{conversation_key}:last_spa_focus", spa_name, timeout=1800)
        reply = [f"💆 Dịch vụ tại **{spa_name}**:"]
        for s in services:
            reply.append(f"- {s['name']}: {s['description']}")
        return self.finalize_reply("\n".join(reply), conversation_key, history)

    def reply_service_detail(self, exact, conversation_key, history):
        s = exact["service"]; spa_name = exact["spa_name"]
        reply = f"💆 **{s['name']}** tại **{spa_name}**:\n{s['description']}"
        cache.set(f"{conversation_key}:last_context", {"spa_name": spa_name, "service_name": s["name"]}, timeout=900)
        cache.set(f"{conversation_key}:last_spa_focus", spa_name, timeout=1800)
        return self.finalize_reply(reply, conversation_key, history)

    def reply_choose_service(self, service_names, conversation_key, history):
        reply = ["Bạn muốn đặt **dịch vụ** nào sau đây:"]
        for i, name in enumerate(service_names, 1):
            reply.append(f"{i}. {name}")
        reply.append("Vui lòng trả lời **số thứ tự** hoặc **tên dịch vụ**.")
        return self.finalize_reply("\n".join(reply), conversation_key, history)

    def reply_choose_spa_for_service(self, service_name, spas, conversation_key, history, slot_label=None):
        header = f"🔎 Dịch vụ **{service_name}** hiện có tại các spa sau"
        if slot_label: header += f" (cho thời gian **{slot_label}**)"
        header += ", bạn muốn đặt ở đâu:"
        lines = [header]
        for i, spa in enumerate(spas, 1):
            lines.append(f"{i}. **{spa['name']}** — {spa['address']}")
        lines.append("Vui lòng trả lời **số thứ tự** hoặc **tên spa**.")
        return self.finalize_reply("\n".join(lines), conversation_key, history)

    # ===== Booking flow helpers =====
    def find_services_in_text(self, message, services_dict):
        msg = self._normalize(message)
        found, all_names = [], set()
        for spa_name, services in services_dict.items():
            for s in services:
                name_norm = self._normalize(s["name"])
                all_names.add(name_norm)
                if name_norm in msg:
                    found.append({"spa_name": spa_name, "service": s}); continue
                tokens = [t for t in name_norm.split() if len(t) >= 3]
                if sum(1 for t in tokens if t in msg) >= 2:
                    found.append({"spa_name": spa_name, "service": s})
        if found:
            return found
        for cand in get_close_matches(msg, list(all_names), n=3, cutoff=0.6):
            for spa_name, services in services_dict.items():
                for s in services:
                    if self._normalize(s["name"]) == cand:
                        found.append({"spa_name": spa_name, "service": s})
        return found

    def reply_choose_service_for_spa(self, spa_name, service_names, conversation_key, history):
        if not service_names:
            return self.finalize_reply(
                f"Hiện **{spa_name}** chưa có danh sách dịch vụ. Bạn có thể nhắn tên dịch vụ muốn đặt không?",
                conversation_key, history
            )
        lines = [f"Bạn muốn đặt **dịch vụ** nào tại **{spa_name}**:"]
        for i, name in enumerate(service_names, 1):
            lines.append(f"{i}. {name}")
        lines.append("Vui lòng trả lời **số thứ tự** hoặc **tên dịch vụ**.")
        return self.finalize_reply("\n".join(lines), conversation_key, history)

    def get_available_slots(self, spa_name):
        base = datetime.now(); opts = []
        for d in range(1, 4):
            day = base + timedelta(days=d)
            for h in [9, 11, 14, 16]:
                dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
                opts.append(dt)
        return [{"label": dt.strftime("%d/%m/%Y %H:%M"), "iso": dt.isoformat()} for dt in opts]

    def ask_booking_info(self, slots, conversation_key, history):
        reply = ["🗓️ Lịch trống gần nhất:"]
        for i, s in enumerate(slots[:8], 1):
            reply.append(f"{i}. {s['label']}")
        reply.append("Vui lòng chọn số slot (ví dụ: 2), hoặc nhập thời gian bạn muốn (dd/mm/yyyy hh:mm).")
        return self.finalize_reply("\n".join(reply), conversation_key, history)

    def parse_datetime_from_message(self, message):
        return self.dt_parser.parse(message)
        # m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})", message.strip())
        # if not m: return None
        # try:
        #     dd, mm, yyyy, HH, MM = map(int, m.groups())
        #     return datetime(yyyy, mm, dd, HH, MM, 0)
        # except Exception:
        #     return None

    def handle_booking_details(self, ctx, message):
        msg = message.strip()

        # Time (giữ nguyên nhánh này cho bước hỏi/confirm; 4.b ở controller đã override nếu user nói kèm giờ)
        if not ctx.get("slot"):
            desired_dt = self.parse_datetime_from_message(msg)
            if desired_dt:
                ctx["slot"] = {"label": desired_dt.strftime("%d/%m/%Y %H:%M"), "iso": desired_dt.isoformat()}
            else:
                m = re.match(r"^\s*(\d{1,2})\s*$", msg)
                if m and ctx.get("available_slots"):
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < len(ctx["available_slots"]):
                        ctx["slot"] = ctx["available_slots"][idx]
                if not ctx.get("slot"):
                    return False, ctx, "Mình chưa bắt được thời gian. Bạn chọn số thứ tự hoặc nhập **dd/mm/yyyy hh:mm** nhé."
        # Name
        # if not ctx.get("customer_name"):
        #     if not re.search(r"\d", msg) and len(msg) >= 2 and msg.lower() not in ["ok", "oke", "yes"]:
        #         ctx["customer_name"] = msg
        #     if not ctx.get("customer_name"):
        #         return False, ctx, "Cho mình xin **tên** của bạn để giữ chỗ nhé."

        # Phone
        # if not ctx.get("phone"):
        #     phone_match = re.search(r"(0\d{9,10}|84\d{9,10}|\+84\d{9,10})", msg.replace(" ", ""))
        #     if phone_match:
        #         ctx["phone"] = phone_match.group(1)
        #     if not ctx.get("phone"):
        #         return False, ctx, "Bạn vui lòng cho mình xin **số điện thoại** (ví dụ: 09xxxxxxxx)."
        # Confirm
        confirm_text = (
            "Xác nhận đặt hẹn:\n"
            f"- Spa: {ctx['spa_name']}\n"
            f"- Dịch vụ: {ctx['service_name']}\n"
            f"- Thời gian: {ctx['slot']['label']}\n"
            # f"- Khách hàng: {ctx['customer_name']}\n"
            # f"- SĐT: {ctx['phone']}\n\n"
            "Bạn xác nhận **ĐỒNG Ý** chứ?"
        )
        if any(kw in msg.lower() for kw in ["đồng ý", "dong y", "xac nhan", "xác nhận", "confirm"]):
            ctx["confirmed"] = True
            return True, ctx, ""
        else:
            return False, ctx, confirm_text

    def confirm_booking(self, ctx):
        return (
            "✅ Đặt hẹn thành công!\n"
            f"- Spa: {ctx['spa_name']}\n"
            f"- Dịch vụ: {ctx['service_name']}\n"
            f"- Thời gian: {ctx['slot']['label']}\n"
            "Hẹn gặp bạn tại spa!"
        )

    # === Appointment ===
    def is_request_for_my_appointments(self, message: str) -> bool:
        msg = self._normalize(message)
        keys = [
            "danh sach lich hen", "danh sach lich hen cua toi", "lich hen cua toi",
            "xem lich hen", "xem dat lich", "xem dat hen", "booking cua toi",
            "cac lich hen cua toi", "lich hen da dat", "lich hen cua minh"
        ]
        return any(k in msg for k in keys)

    def add_appointment(self, user_id: str, ctx: dict):
        appt_key = f"appointments:{user_id}"
        appts = cache.get(appt_key) or []
        appt_id = f"APPT-{int(datetime.now().timestamp())}"
        appts.append({
            "id": appt_id,
            "spa_name": ctx.get("spa_name"),
            "service_name": ctx.get("service_name"),
            "slot_label": ctx.get("slot", {}).get("label"),
            "slot_iso": ctx.get("slot", {}).get("iso"),
            # "customer_name": ctx.get("customer_name"),
            # "phone": ctx.get("phone"),
            "created_at": datetime.now().isoformat()
        })
        cache.set(appt_key, appts, timeout=30 * 24 * 3600)
        return appt_id

    def get_appointments(self, user_id: str):
        return cache.get(f"appointments:{user_id}") or []

    def reply_my_appointments(self, user_id: str, conversation_key: str, history: list):
        appts = self.get_appointments(user_id)
        if not appts:
            return self.finalize_reply("Hiện bạn **chưa có lịch hẹn** nào trong hệ thống.", conversation_key, history)

        def key_func(a):
            try:
                return datetime.fromisoformat(a.get("slot_iso"))
            except Exception:
                return datetime.max

        appts_sorted = sorted(appts, key=key_func)

        lines = ["📒 **Lịch hẹn của bạn:**"]
        for i, a in enumerate(appts_sorted, 1):
            lines.append(
                f"{i}. {a.get('slot_label','(chưa rõ)')} — **{a.get('spa_name','?')}** / {a.get('service_name','?')}\n"
                f"   Mã lịch hẹn: `{a.get('id')}`"
            )
        return self.finalize_reply("\n".join(lines), conversation_key, history)

    # ===== GPT =====
    def is_general_skin_question_gpt(self, message, client: OpenAI):
        system_msg = (
            "Bạn là một bộ lọc phân loại câu hỏi.\n"
            "Nếu người dùng hỏi về các vấn đề liên quan đến chăm sóc da, làm đẹp, mụn, thâm, nám, lão hóa, dưỡng da, spa nói chung (nhưng không hỏi tên dịch vụ cụ thể), trả lời: YES.\n"
            "Nếu không phải, trả lời: NO.\n"
            "Chỉ trả về một từ duy nhất: YES hoặc NO."
        )
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": message}],
        )
        return completion.choices[0].message.content.strip().upper() == "YES"

    def reply_with_gpt_history(self, client: OpenAI, history, message, user_id):
        conversation_key = f"chat:{user_id}"
        spa_info = "\n".join([f"- {spa['name']} — {spa['address']}" for spa in spa_locations])
        system_prompt = f"""
Bạn là trợ lý tư vấn spa & chăm sóc da.

DANH SÁCH SPA:
{spa_info}

QUY TẮC TRẢ LỜI:
1) Danh sách spa theo vị trí → liệt kê đúng thành phố (chỉ trong danh sách).
2) Tên spa → giới thiệu spa.
3) Danh sách dịch vụ của spa → liệt kê dịch vụ của spa đó.
4) Nếu người dùng nêu tên dịch vụ → giới thiệu chi tiết; nếu có ý định đặt hẹn → chuyển luồng đặt hẹn.
5) Đặt hẹn → dùng thời gian user đã cung cấp (nếu có), hỏi tên/SĐT & xác nhận; không gợi ý slot nếu đã có thời gian.
6) Skincare → trả lời đúng trọng tâm skincare.
7) Ngoài phạm vi → nói: "Xin lỗi, tôi chỉ hỗ trợ các câu hỏi về làm đẹp, chăm sóc da và spa."
8) Văn phong: thân thiện, rõ ràng, ngắn gọn, bám đúng chủ đề của tin nhắn.
"""
        if len(history) > 20:
            history = history[-20:]
        messages = [{"role": "system", "content": system_prompt}] + history
        try:
            completion = client.chat.completions.create(model="gpt-4o", messages=messages)
            reply = completion.choices[0].message.content.strip()
        except Exception:
            reply = "⚠️ Đã có lỗi xảy ra khi gọi AI. Vui lòng thử lại sau."
        history.append({"role": "assistant", "content": reply})
        cache.set(conversation_key, history, timeout=86400)
        return self.json_response(reply)