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
from zoneinfo import ZoneInfo


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

    def reset_time_fields(self, ctx: dict) -> dict:
        """Xoá sạch thông tin thời gian để tránh dính slot cũ."""
        for k in ("slot", "available_slots", "confirmed"):
            ctx.pop(k, None)
        return ctx

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
    
    def is_skin_question_local(self, message: str) -> bool:
        """
        Nhận diện nhanh các câu skincare chung (mụn, thâm, nám, routine, retinol...).
        Chỉ trả True nếu KHÔNG có ý định booking/ dịch vụ cụ thể.
        """
        msg = self._normalize(message)

        # Từ khóa chủ đề skincare (triệu chứng | routine | hoạt chất | bước skincare)
        skin_terms = [
            "mun", "mun an", "mun viem", "mun dau den", "mun dau trang",
            "tham", "nam", "tan nhang", "lo chan long", "do dau", "da kho",
            "kich ung", "kich ung da", "viem da",
            "skincare", "routine", "chuong trinh duong da", "duong am", "tay da chet",
            "tay trang", "sua rua mat", "cleanser", "toner", "serum", "kem chong nang",
            "retinol", "tre", "bha", "aha", "paha", "niacinamide", "vitamin c", "ha", "hyaluronic"
        ]
        ask_terms = [
            "lam sao", "nhu the nao", "giai phap", "nen dung", "chi minh", "tu van",
            "cach tri", "tri nhu the nao", "co nen", "huong dan", "khac phuc", "meo"
        ]

        has_skin = any(t in msg for t in skin_terms)
        has_ask  = any(t in msg for t in ask_terms) or "?" in message

        # Không lẫn với booking/dịch vụ
        is_booking = self.is_booking_request(message)
        looks_service_list = ("dich vu" in msg) or ("danh sach" in msg) or ("bang gia" in msg)

        return (has_skin and (has_ask or True)) and (not is_booking) and (not looks_service_list)

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

    def is_request_for_service_list(self, message):
        if self.is_booking_request(message):
            return False
        msg = self._normalize(message)

        # Ưu tiên khi có 'dich vu' + ý hỏi/liệt kê
        if "dich vu" in msg:
            cues = [" nao", " gi", " tot", "goi y", "danh sach", "liet ke",
                    "co nhung", "nhung gi", "gom", "bao gom", "goi nao", "nen dung"]
            if any(c in msg for c in cues):
                return True

        # Cụm list tường minh
        if any(c in msg for c in ["danh sach", "liet ke", "bang gia", "bao gia"]):
            return True

        return False
    
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
    
    def find_service_in_text_for_spa(self, message: str, spa_name: str):
        """
        Ưu tiên bắt dịch vụ CHỈ trong phạm vi spa_name (focus đúng spa).
        Trả về tên dịch vụ (str) hoặc None nếu không nhận được.
        """
        msg = self._normalize(message)
        services = spa_services.get(spa_name, [])
        if not services:
            return None

        # (a) khớp nguyên cụm
        for s in services:
            if self._normalize(s["name"]) in msg:
                return s["name"]

        # (b) chấm điểm theo overlap token (>=2 token là đạt)
        best_name, best_score = None, 0
        for s in services:
            name_norm = self._normalize(s["name"])
            toks = [t for t in name_norm.split() if len(t) >= 2]
            score = sum(1 for t in toks if t in msg)
            if score > best_score:
                best_score, best_name = score, s["name"]
        if best_score >= 2:
            return best_name

        # (c) fuzzy nhẹ
        from difflib import get_close_matches
        names_norm = [self._normalize(s["name"]) for s in services]
        match = get_close_matches(msg, names_norm, n=1, cutoff=0.6)
        if match:
            idx = names_norm.index(match[0])
            return services[idx]["name"]

        return None

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

    # --- BỔ SUNG: nhận diện đổi giờ ---
    def is_change_time_request(self, message: str) -> bool:
        msg = self._normalize(message)
        keys = [
            "doi gio", "doi thoi gian", "doi lich", "sua gio", "chinh gio",
            "chuyen sang", "doi sang", "doi qua", "reschedule", "change time",
            "doi thoi diem", "doi khung gio", "doi slot", "doi gio hen"
        ]
        return any(k in msg for k in keys)

    def handle_booking_details(self, ctx, message):
        msg = message.strip()

        # Nếu đã có slot và người dùng nói đổi giờ hoặc nhập giờ mới → cập nhật trước
        already_has_slot = bool(ctx.get("slot"))
        wants_change_time = getattr(self, "is_change_time_request", lambda _m: False)(msg)
        parsed_new_dt = self.parse_datetime_from_message(msg)

        if already_has_slot and (wants_change_time or parsed_new_dt):
            if parsed_new_dt:
                prev_label = ctx["slot"]["label"]
                ctx["previous_slot"] = ctx["slot"]
                ctx["slot"] = {"label": parsed_new_dt.strftime("%d/%m/%Y %H:%M"),
                            "iso": parsed_new_dt.isoformat()}
                ctx.pop("available_slots", None)
                ctx.pop("confirmed", None)
                ask = (
                    "⏰ Đã cập nhật **thời gian** đặt hẹn:\n"
                    f"- Trước đó: {prev_label}\n"
                    f"- Mới: {ctx['slot']['label']}\n\n"
                    "Bạn xác nhận **ĐỒNG Ý** chứ?"
                )
                return False, ctx, ask
            else:
                # muốn đổi nhưng chưa nêu giờ → gợi ý slot
                if ctx.get("spa_name"):
                    slots = self.get_available_slots(ctx["spa_name"])
                    ctx["available_slots"] = slots
                    ask = ["Bạn muốn đổi sang **thời gian** nào? Lịch trống gần nhất:"]
                    for i, s in enumerate(slots[:8], 1):
                        ask.append(f"{i}. {s['label']}")
                    ask.append("Vui lòng **chọn số** hoặc nhập **dd/mm/yyyy hh:mm**.")
                    return False, ctx, "\n".join(ask)
                else:
                    return False, ctx, "Bạn muốn đổi sang **thời gian nào**? (định dạng **dd/mm/yyyy hh:mm**)."

        # Nếu CHƯA có slot → bắt thời gian
        if not ctx.get("slot"):
            desired_dt = self.parse_datetime_from_message(msg)
            if desired_dt:
                ctx["slot"] = {"label": desired_dt.strftime("%d/%m/%Y %H:%M"),
                            "iso": desired_dt.isoformat()}
            else:
                m = re.match(r"^\s*(\d{1,2})\s*$", msg)
                if m and ctx.get("available_slots"):
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < len(ctx["available_slots"]):
                        ctx["slot"] = ctx["available_slots"][idx]
                if not ctx.get("slot"):
                    return False, ctx, "Mình chưa bắt được thời gian. Bạn chọn **số thứ tự** hoặc nhập **dd/mm/yyyy hh:mm** nhé."

        # Xác nhận (KHÔNG hỏi tên / SĐT)
        confirm_text = (
            "Xác nhận đặt hẹn:\n"
            f"- Spa: {ctx['spa_name']}\n"
            f"- Dịch vụ: {ctx['service_name']}\n"
            f"- Thời gian: {ctx['slot']['label']}\n"
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
        """
        Chỉ bắt khi:
        - Có động từ tra cứu + 'lịch hẹn' (xem/kiểm tra/danh sách/liệt kê ... lịch hẹn)
        HOẶC
        - Có 'lịch hẹn của tôi/của mình/booking của tôi'
        → KHÔNG bắt những câu 'đặt hẹn', 'muốn đặt hẹn', ...
        """
        msg = self._normalize(message)

        # 1) cụm sở hữu 'của tôi / của mình' + 'lịch hẹn'
        if ("lich hen" in msg or "booking" in msg) and any(
            own in msg for own in ["cua toi", "cua minh", "toi"]
        ):
            return True

        # 2) động từ tra cứu + 'lịch hẹn'
        lookup_verbs = ["xem", "kiem tra", "kiemtra", "danh sach", "liet ke", "liệt kê"]
        if ("lich hen" in msg or "booking" in msg) and any(v in msg for v in lookup_verbs):
            return True

        return False

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
    
    # ===== Dynamic appointment-range intent =====
    def _now_vn(self):
        return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))

    def _ensure_vn(self, dt: datetime):
        if dt is None: return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        return dt.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))

    def _safe_fromiso(self, iso_str: str):
        try:
            return datetime.fromisoformat(iso_str)
        except Exception:
            return None

    def _add_months(self, d: datetime, months: int):
        y = d.year + (d.month - 1 + months) // 12
        m = (d.month - 1 + months) % 12 + 1
        # clamp day
        last_day = 28
        for day in [31,30,29,28]:
            try:
                return d.replace(year=y, month=m, day=min(d.day, day))
            except ValueError:
                continue
        return d.replace(year=y, month=m, day=28)

    def _day_range(self, date_obj: datetime):
        start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end

    def _week_range(self, date_obj: datetime):
        # tuần bắt đầu Thứ Hai
        start = (date_obj - timedelta(days=date_obj.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        return start, end

    def _month_range(self, date_obj: datetime):
        start = date_obj.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = self._add_months(start, 1)
        return start, end

    def is_appointments_lookup_intent(self, message: str) -> bool:
        """
        Ý định xem/kiểm tra lịch hẹn theo mốc thời gian (hôm nay/mai/hôm qua/tuần/tháng/…)
        hoặc hỏi dạng 'có lịch hẹn ... không'.
        """
        msg = self._normalize(message)

        has_calendar = any(k in msg for k in ["lich hen", "dat hen", "booking", "lich"])
        if not has_calendar:
            return False

        # Các cụm thời gian phổ biến
        time_phrases = [
            "hom nay", "ngay mai", "hom qua",
            "tuan nay", "tuan sau", "tuan truoc",
            "thang nay", "thang sau", "thang truoc",
            "this week", "next week", "last week",
            "this month", "next month", "last month",
            "tu ", "toi ", "tới ", "den ", "đến ",  # 'từ ... đến ...'
            "trong ", "ngay toi", "ngay toi", "tuan toi", "thang toi", "qua", "yesterday", "today", "tomorrow"
        ]
        has_time_phrase = any(tp in msg for tp in time_phrases)

        # Câu nghi vấn kiểu 'có ... không'
        has_yesno_ask = (" co " in f" {msg} ") and (" khong" in msg or " không" in message)

        # Các động từ tra cứu (để mở rộng cover)
        has_lookup_verb = any(k in msg for k in ["xem", "kiem tra", "kiemtra", "danh sach", "liet ke", "liệt kê"])

        return has_time_phrase or has_yesno_ask or has_lookup_verb

    def parse_appointment_range(self, message: str):
        """
        Trả về (start_dt, end_dt, title) nếu nhận ra khoảng thời gian tra cứu; ngược lại None.
        Hỗ trợ: hôm nay/mai/hôm qua, tuần này/trước/sau, tháng này/trước/sau,
        'trong N ngày/tuần/tháng tới/qua', 'từ dd/mm[/yyyy] đến dd/mm[/yyyy]'.
        """
        msg = self._normalize(message)
        now = self._now_vn()

        # --- 1) Khoảng ngày dạng "từ ... đến ..."
        m = re.search(r"tu\s+(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?\s+(?:den|toi)\s+(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?", msg)
        if m:
            d1,m1,y1,d2,m2,y2 = m.groups()
            y1 = int(y1) if y1 else now.year
            y2 = int(y2) if y2 else now.year
            start = self._ensure_vn(datetime(int(y1), int(m1), int(d1), 0, 0))
            end_day = self._ensure_vn(datetime(int(y2), int(m2), int(d2), 0, 0))
            end = end_day + timedelta(days=1)  # inclusive day-range
            title = f"📅 **Lịch hẹn từ {int(d1):02d}/{int(m1):02d} đến {int(d2):02d}/{int(m2):02d}:**"
            return start, end, title

        # --- 2) Hôm nay / ngày mai / hôm qua
        if "hom nay" in msg or "today" in msg:
            s,e = self._day_range(now)
            return s,e,"📅 **Lịch hẹn hôm nay của bạn:**"
        if "ngay mai" in msg or "tomorrow" in msg:
            s = (now + timedelta(days=1))
            s,e = self._day_range(s)
            return s,e,"📅 **Lịch hẹn ngày mai của bạn:**"
        if "hom qua" in msg or "yesterday" in msg:
            s = (now - timedelta(days=1))
            s,e = self._day_range(s)
            return s,e,"📅 **Lịch hẹn hôm qua của bạn:**"

        # --- 3) Tuần này / tuần sau / tuần trước
        if "tuan nay" in msg or "this week" in msg:
            s,e = self._week_range(now)
            end_disp = e - timedelta(days=1)
            title = f"📅 **Lịch hẹn tuần này ({s.strftime('%d/%m')}–{end_disp.strftime('%d/%m')}):**"
            return s,e,title
        if "tuan sau" in msg or "next week" in msg:
            s,e = self._week_range(now + timedelta(days=7))
            end_disp = e - timedelta(days=1)
            title = f"📅 **Lịch hẹn tuần sau ({s.strftime('%d/%m')}–{end_disp.strftime('%d/%m')}):**"
            return s,e,title
        if "tuan truoc" in msg or "last week" in msg:
            s,e = self._week_range(now - timedelta(days=7))
            end_disp = e - timedelta(days=1)
            title = f"📅 **Lịch hẹn tuần trước ({s.strftime('%d/%m')}–{end_disp.strftime('%d/%m')}):**"
            return s,e,title

        # --- 4) Tháng này / tháng sau / tháng trước
        if "thang nay" in msg or "this month" in msg:
            s,e = self._month_range(now)
            end_disp = e - timedelta(days=1)
            title = f"📅 **Lịch hẹn tháng này ({s.strftime('%m/%Y')}):**"
            return s,e,title
        if "thang sau" in msg or "next month" in msg:
            s,e = self._month_range(self._add_months(now, 1))
            title = f"📅 **Lịch hẹn tháng sau ({s.strftime('%m/%Y')}):**"
            return s,e,title
        if "thang truoc" in msg or "last month" in msg:
            s,e = self._month_range(self._add_months(now, -1))
            title = f"📅 **Lịch hẹn tháng trước ({s.strftime('%m/%Y')}):**"
            return s,e,title

        # --- 5) “trong N ngày/tuần/tháng tới/qua”
        m = re.search(r"trong\s+(\d+)\s+(ngay|tuan|thang)\s+(toi|toi|tới|sau|qua)", msg)
        if m:
            n, unit, dirn = m.groups()
            n = int(n)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if unit == "ngay":
                delta = timedelta(days=n)
                if dirn in ("qua",):
                    return start - delta, start, f"📅 **Lịch hẹn {n} ngày qua:**"
                else:
                    return start, start + delta, f"📅 **Lịch hẹn {n} ngày tới:**"
            if unit == "tuan":
                delta = timedelta(weeks=n)
                if dirn in ("qua",):
                    return start - delta, start, f"📅 **Lịch hẹn {n} tuần qua:**"
                else:
                    return start, start + delta, f"📅 **Lịch hẹn {n} tuần tới:**"
            if unit == "thang":
                if dirn in ("qua",):
                    s = self._add_months(start, -n)
                    return s, start, f"📅 **Lịch hẹn {n} tháng qua:**"
                else:
                    e = self._add_months(start, n)
                    return start, e, f"📅 **Lịch hẹn {n} tháng tới:**"

        # Không nhận ra
        return None
    
    def has_time_expression(self, message: str) -> bool:
        """
        Trả về True nếu turn hiện tại có bất kỳ diễn đạt thời gian nào.
        Dùng để quyết định có xoá slot cũ hay không.
        """
        raw = (message or "")
        norm = self._normalize(raw)

        # 1) Có parse được ngày/giờ rõ ràng -> có thời gian
        try_dt = self.parse_datetime_from_message(raw)
        if try_dt:
            return True

        # 2) Từ khoá thời gian thường gặp (không đủ để parse nhưng là tín hiệu user đang nói về giờ/ngày)
        time_keywords = [
            # buổi
            "sang", "trua", "chieu", "toi", "dem", "khuya",
            # chỉ ngày
            "hom nay", "ngay mai", "hom qua", "tuan nay", "tuan sau", "tuan truoc",
            "thang nay", "thang sau", "thang truoc",
            # am/pm
            " am", " pm",
            # cấu trúc giờ tiếng Việt
            " gio", " gio ", " gio.", " gio,", "g", "h", "kem", "ruoi", "rưỡi",
            # định dạng số giờ
            ":",  # 09:00
        ]
        if any(k in f" {norm} " for k in time_keywords):
            return True

        # 3) Mẫu số đơn giản: "9h", "9 g", "9 gio", "9 giờ"
        if re.search(r"\b\d{1,2}\s*(h|g|gio|giờ)\b", norm):
            return True

        return False

    def is_confirm_message(self, message: str) -> bool:
        msg = self._normalize(message)
        return any(k in msg for k in ["dong y", "xac nhan", "confirm", "ok", "oke", "okie"])

    def find_service_in_text_for_spa(self, message: str, spa_name: str):
        """
        Match dịch vụ **trong phạm vi 1 spa cụ thể**.
        """
        msg = self._normalize(message)
        services = [s["name"] for s in spa_services.get(spa_name, [])]
        norm_map = {self._normalize(n): n for n in services}
        # khớp full cụm
        for norm_name, original in norm_map.items():
            if norm_name in msg:
                return original
        # khớp overlap đơn giản
        best, score = None, 0
        for norm_name, original in norm_map.items():
            toks = [t for t in norm_name.split() if len(t) >= 2]
            sc = sum(1 for t in toks if t in msg)
            if sc > score:
                score, best = sc, original
        return best if score > 0 else None

    def infer_service_from_history(self, history):
        """
        Fallback: tìm dịch vụ + spa được nhắc gần nhất trong history khi người dùng nói 'dịch vụ này'.
        """
        for h in reversed(history):
            content = self._normalize(h.get("content", ""))
            for spa_name, services in spa_services.items():
                for s in services:
                    if self._normalize(s["name"]) in content:
                        return {"spa_name": spa_name, "service_name": s["name"]}
        return None
    #...

    def reply_my_appointments_in_range(self, user_id: str, start: datetime, end: datetime, title: str, conversation_key: str, history: list):
        appts = self.get_appointments(user_id)
        items = []
        if appts:
            s_vn, e_vn = self._ensure_vn(start), self._ensure_vn(end)
            for a in appts:
                dt = self._safe_fromiso(a.get("slot_iso"))
                if not dt: continue
                dvn = self._ensure_vn(dt)
                if s_vn <= dvn < e_vn:
                    items.append(a)
            items.sort(key=lambda x: self._ensure_vn(self._safe_fromiso(x.get("slot_iso"))) or datetime.max)

        if not items:
            return self.finalize_reply(f"{title}\nKhông có lịch hẹn nào trong khoảng thời gian này.", conversation_key, history)

        lines = [title]
        for i, a in enumerate(items, 1):
            lines.append(
                f"{i}. {a.get('slot_label','(chưa rõ)')} — **{a.get('spa_name','?')}** / {a.get('service_name','?')}\n"
                f"   Mã lịch hẹn: `{a.get('id')}`"
            )
        return self.finalize_reply("\n".join(lines), conversation_key, history)
    def reset_time_if_not_in_message(self, ctx: dict, message: str):
        """Xoá slot/available_slots nếu tin nhắn hiện tại không có thời gian.
        Tránh việc dùng nhầm slot từ context cũ."""
        if self.parse_datetime_from_message(message) is None:
            ctx.pop("slot", None)
            ctx.pop("available_slots", None)
            # tuỳ chọn: đánh dấu nguồn slot
            ctx.pop("slot_source", None)
        return ctx
    
    # --- alias helpers ---
    def _acronym(self, s: str) -> str:
        # Lấy chữ cái đầu mỗi từ viết hoa hoặc từ có chữ cái
        parts = re.findall(r"[A-Za-zÀ-Ỵà-ỵ]+", s)
        ac = "".join(p[0] for p in parts if p)
        return ac.upper()

    def build_spa_alias_index(self, spa_names):
        """
        Trả về dict: {alias_norm: canonical_spa_name}
        Cache 1 ngày để tái dùng.
        """
        cache_key = "spa_alias_index_v1"
        alias_map = cache.get(cache_key)
        if alias_map:
            return alias_map

        alias_map = {}
        for name in spa_names:
            norm_full = self._normalize(name)                # "tham my vien pmt"
            tokens = [t for t in norm_full.split() if t not in ("spa", "tham", "my", "vien", "tmv")]
            last_tok = tokens[-1] if tokens else None        # "pmt" / "serenity" / "bella" ...
            ac = self._acronym(name) or None                 # "PMT"

            # Tập alias gốc
            aliases = {
                norm_full,
                norm_full.replace(" spa", "").replace("tmv ", "").strip(),
            }

            # Alias theo hậu tố
            if last_tok and len(last_tok) >= 3:
                aliases.add(last_tok)

            # Alias acronym (PMT…)
            if ac and len(ac) >= 2:
                aliases.add(ac.lower())

            # Biến thể có/bỏ từ 'spa'
            aliases.add(("spa " + (last_tok or "")).strip())
            if last_tok:
                aliases.add((last_tok + " spa").strip())

            # Lưu vào map
            for a in aliases:
                a_norm = self._normalize(a)
                if a_norm:
                    alias_map[a_norm] = name

        cache.set(cache_key, alias_map, timeout=86400)
        return alias_map

    def detect_spa_in_message(self, message, spa_names):
        """
        Ưu tiên match alias (PMT, Serenity...) -> trả về tên spa chuẩn.
        Fallback: chứa nguyên tên bỏ dấu; fuzzy nhẹ khi cần.
        """
        msg_norm = self._normalize(message)
        alias_map = self.build_spa_alias_index(spa_names)

        # 1) match theo alias (ưu tiên)
        hits = []
        for alias_norm, canonical in alias_map.items():
            # match theo word-boundary để tránh trùng lặp bậy
            if re.search(rf"\b{re.escape(alias_norm)}\b", msg_norm):
                hits.append((len(alias_norm), canonical))
        if hits:
            # chọn alias dài nhất để giảm mơ hồ
            hits.sort(reverse=True)
            return hits[0][1]

        # 2) chứa nguyên tên đầy đủ (bỏ dấu)
        for name in spa_names:
            if self._normalize(name) in msg_norm:
                return name

        # 3) fuzzy nhẹ
        cand = get_close_matches(msg_norm, [self._normalize(s) for s in spa_names], n=1, cutoff=0.6)
        if cand:
            return next((s for s in spa_names if self._normalize(s) == cand[0]), None)

        return None

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