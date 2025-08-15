from apps.dto.bot_dto import BotDto
from apps.controllers._base_controller import BaseController
import os
from openai import OpenAI
import re
from apps.utils.spa_locations import spa_locations
from apps.utils.spa_services import spa_services
from apps.extensions import cache
from apps.vector.training_vector import TrainingVector
from flask_restx import Resource

# load_dotenv()
# openai.api_key = os.getenv("OPENAI_API_KEY", "")

def is_request_for_spa_intro(message, spa_name):
    message_lower = message.lower()
    name_lower = spa_name.lower()

    # Nếu chỉ đơn giản là tên spa → yêu cầu giới thiệu
    if message_lower.strip() == name_lower:
        return True

    # Một số cách hỏi phổ biến để giới thiệu spa
    patterns = [
        fr"giới thiệu.*{re.escape(name_lower)}",
        fr"{re.escape(name_lower)}.*là gì",
        fr"thông tin.*{re.escape(name_lower)}",
        fr"{re.escape(name_lower)}.*ở đâu",
        fr"{re.escape(name_lower)}.*có.*tốt.*không",
    ]

    return any(re.search(p, message_lower) for p in patterns)


@BotDto.api.route('/messages')
class Message(BaseController):
  def get(self):
    return self.json_response([])
  
  @BotDto.api.expect(BotDto.post_message, validate=True)
  def post(self):
    message = self.get_request()['message']
    client = OpenAI(api_key=os.getenv('A_SECRET_KEY'))
    # system_prompt = """
    # Bạn là một chuyên gia tư vấn spa và thẩm mỹ viện.
    # Bạn **chỉ được trả lời** các câu hỏi liên quan đến:
    # - chăm sóc da, tóc, cơ thể
    # - các liệu trình spa, thẩm mỹ
    # - tư vấn làm đẹp, sản phẩm dưỡng da, chăm sóc sau dịch vụ
    #
    # Nếu người dùng hỏi về chủ đề ngoài lĩnh vực đó (như chính trị, thể thao, IT,...), bạn phải trả lời:
    # "Xin lỗi, tôi chỉ hỗ trợ các câu hỏi về làm đẹp, chăm sóc da và spa."
    #
    # Trả lời thân thiện, rõ ràng và ngắn gọn.
    # """

    spa_locations = [
      {"name": "Spa Lily", "address": "123 Lê Lợi, Quận 1, TP. Hồ Chí Minh"},
      {"name": "Thẩm mỹ viện Hoa Mai", "address": "456 Hai Bà Trưng, Quận 3, TP. Hồ Chí Minh"},
      {"name": "PMT", "address": "456 Hai Bà Trưng, Quận 3, TP. Hồ Chí Minh"},
      {"name": "Bella Spa", "address": "789 Nguyễn Văn Cừ, Quận 5, TP. Hồ Chí Minh"},
      {"name": "Serenity Spa", "address": "88 Phan Đình Phùng, TP. Đà Nẵng"},
    ]
    spa_info = "\n".join([f"- {spa['name']} — {spa['address']}" for spa in spa_locations])

    system_prompt = f"""
        Bạn là một chuyên gia tư vấn spa và thẩm mỹ viện. Bạn có danh sách các spa sau:

        {spa_info}

        Nếu người dùng hỏi tìm spa ở tỉnh/thành nào, bạn chỉ được gợi ý từ danh sách trên.

        Nếu câu hỏi không liên quan đến làm đẹp hoặc spa, hãy trả lời: "Xin lỗi, tôi chỉ hỗ trợ các câu hỏi về làm đẹp, chăm sóc da và spa."

        Trả lời thân thiện, đúng thông tin.
        """

    completion = client.chat.completions.create(
      model="gpt-4o",
      messages=[
        {"role": "system", "content": system_prompt},
        {
          "role": "user",
          "content": message,
        },
      ],
    )
    return self.json_response(completion.choices[0].message.content)

#######
@BotDto.api.route('/messages/v2/<user_id>')
class GetMessageV2(BaseController):
    @BotDto.api.param('user_id', '', _in='path', required=True)
    def get(self, user_id):
        conversation_key = f"chat:{user_id}"
        history = cache.get(conversation_key) or []
        return self.json_response(history)

    @BotDto.api.param('user_id', '', _in='path', required=True)
    def delete(self, user_id):
        conversation_key = f"chat:{user_id}"
        cache.delete(conversation_key)
        return self.json_response({"message": "Conversation history deleted."})

@BotDto.api.route('/messages/v2')
class MessageV2(BaseController, Resource):
    @BotDto.api.expect(BotDto.post_message, validate=True)
    def post(self):
        # --- Input ---
        req = self.get_request() or {}
        message = req.get('message', '')
        user_id = req.get('user_id') or 123

        conversation_key = f"chat:{user_id}"
        history = cache.get(conversation_key) or []
        history.append({"role": "user", "content": message})

        helper = TrainingVector()
        client = OpenAI(api_key=os.getenv("A_SECRET_KEY"))
        ctx = helper.get_booking_context(user_id) or {"active": False}

        # ===== Guard: chuyển sang flow khác → dừng booking đang treo =====
        if helper.is_request_for_spa_list(message) and ctx.get("active"):
            helper.clear_booking_context(user_id); ctx = {"active": False}
        if hasattr(helper, "is_additional_booking") and helper.is_additional_booking(message):
            helper.clear_booking_context(user_id); ctx = {"active": False}

        # ===== 0) Tra cứu lịch hẹn theo khoảng thời gian =====
        if helper.is_appointments_lookup_intent(message):
            parsed = helper.parse_appointment_range(message)
            if parsed:
                s, e, title = parsed
                return helper.reply_my_appointments_in_range(user_id, s, e, title, conversation_key, history)

        # ===== 1) Skincare chung (ưu tiên sớm) =====
        if getattr(helper, "is_skin_question_local", lambda _m: False)(message) or helper.is_general_skin_question_gpt(message, client):
            if ctx.get("active"): helper.clear_booking_context(user_id)
            return helper.reply_with_gpt_history(client, history, message, user_id)

        # ===== 2) Danh sách spa theo vị trí =====
        city = helper.extract_city_from_message(message, helper.extract_city_keywords(spa_locations))
        if city and helper.is_request_for_spa_list(message):
            return helper.reply_spa_list(city, helper.find_spas_by_city(spa_locations, city), conversation_key, history)

        # ===== 3) Tên spa → giới thiệu spa =====
        spa_names = list(spa_services.keys())
        spa_from_msg = helper.detect_spa_in_message(message, spa_names)
        if spa_from_msg and helper.is_request_for_spa_intro(message, spa_from_msg):
            return helper.reply_spa_intro(spa_from_msg, spa_locations, conversation_key, history)

        # ===== 4) Danh sách dịch vụ (luôn clear slot cũ để không dính giờ) =====
        if helper.is_request_for_service_list(message):
            target_spa = spa_from_msg or ctx.get("spa_name") or cache.get(f"{conversation_key}:last_spa_focus")
            helper.clear_booking_context(user_id)
            if target_spa:
                return helper.reply_service_list(target_spa, spa_services, conversation_key, history)
            last_list = helper.get_last_spa_list(conversation_key)
            if last_list:
                picked = helper.resolve_spa_selection_from_message(message, last_list)
                if picked: return helper.reply_service_list(picked, spa_services, conversation_key, history)
                return helper.reply_choose_spa_from_last_list(conversation_key, history, note="để xem danh sách dịch vụ")
            return helper.finalize_reply("Bạn muốn xem **danh sách dịch vụ** của **spa nào** ạ?", conversation_key, history)

        # ===== 5) BOOKING (chỉ xác nhận khi đã đủ SPA + DỊCH VỤ + THỜI GIAN) =====
        if helper.is_booking_request(message) or ctx.get("active"):
            ctx["active"] = True

            # 5.a — KHÔNG để dính giờ cũ
            has_time_expr = getattr(helper, "has_time_expression", lambda m: bool(helper.parse_datetime_from_message(m)))(message)
            is_confirm = getattr(helper, "is_confirm_message", lambda m: False)(message)
            if not has_time_expr and not is_confirm:
                ctx.pop("slot", None); ctx.pop("available_slots", None); ctx.pop("confirmed", None)

            new_dt = helper.parse_datetime_from_message(message)
            if new_dt:
                ctx["slot"] = {"label": new_dt.strftime("%d/%m/%Y %H:%M"), "iso": new_dt.isoformat()}
                ctx.pop("available_slots", None); ctx.pop("confirmed", None)

            # 5.b — Xác định SPA (từ câu nói > last_spa_focus)
            if spa_from_msg and ctx.get("spa_name") != spa_from_msg:
                ctx["spa_name"] = spa_from_msg
                # đổi spa ⇒ must reset time to avoid accidental confirm
                ctx.pop("slot", None); ctx.pop("available_slots", None); ctx.pop("confirmed", None)
            if not ctx.get("spa_name"):
                last_focus = cache.get(f"{conversation_key}:last_spa_focus")
                if last_focus: ctx["spa_name"] = last_focus

            # Nếu chưa biết spa → hỏi spa (KHÔNG đi tiếp)
            if not ctx.get("spa_name"):
                helper.set_booking_context(user_id, ctx)
                last_list = helper.get_last_spa_list(conversation_key)
                if last_list:
                    return helper.reply_choose_spa_from_last_list(conversation_key, history, note="để tiến hành đặt hẹn")
                short = [f"- **{s['name']}** — {s['address']}" for s in spa_locations]
                return helper.finalize_reply(
                    "Bạn muốn đặt tại **spa nào**? Bạn có thể trả lời tên spa.\n" + "\n".join(short[:8]),
                    conversation_key, history
                )

            # 5.c — Bắt DỊCH VỤ (KHÔNG tự đoán)
            # 1) Nếu vừa gợi ý candidates → đọc chọn
            if ctx.get("service_candidates") and not ctx.get("service_name"):
                chosen = helper.resolve_service_selection_from_message(message, ctx["service_candidates"])
                if chosen:
                    if ctx.get("service_name") and ctx["service_name"] != chosen:
                        ctx.pop("slot", None); ctx.pop("available_slots", None); ctx.pop("confirmed", None)
                    ctx["service_name"] = chosen
                    ctx.pop("service_candidates", None)

            # 2) “dịch vụ này” → lấy từ last_context (nếu cùng spa), KHÔNG inference mơ hồ
            if not ctx.get("service_name") and helper.is_referring_prev_service(message):
                last = cache.get(f"{conversation_key}:last_context")
                if last and (not last.get("spa_name") or last.get("spa_name") == ctx["spa_name"]):
                    ctx["service_name"] = last.get("service_name")

            # 3) Ưu tiên bắt tên dịch vụ xuất hiện rõ trong câu (chỉ trong spa hiện tại)
            if not ctx.get("service_name"):
                pick_in_spa = getattr(helper, "find_service_in_text_for_spa", lambda *_: None)(message, ctx["spa_name"])
                if pick_in_spa:
                    if ctx.get("service_name") and ctx["service_name"] != pick_in_spa:
                        ctx.pop("slot", None); ctx.pop("available_slots", None); ctx.pop("confirmed", None)
                    ctx["service_name"] = pick_in_spa

            # 4) Nếu vẫn chưa có dịch vụ → HỎI CHỌN (bắt buộc), không tự chọn default
            if not ctx.get("service_name"):
                service_list = [s["name"] for s in spa_services.get(ctx["spa_name"], [])]
                if not service_list:
                    helper.set_booking_context(user_id, ctx)
                    return helper.finalize_reply(f"Hiện **{ctx['spa_name']}** chưa cập nhật dịch vụ. Bạn muốn chọn spa khác không?", conversation_key, history)
                ctx["service_candidates"] = service_list
                helper.set_booking_context(user_id, ctx)
                return helper.reply_choose_service_for_spa(ctx["spa_name"], service_list, conversation_key, history)

            # 5.d — Nếu chưa có thời gian → gợi ý slot (KHÔNG xác nhận)
            if not ctx.get("slot"):
                slots = helper.get_available_slots(ctx["spa_name"])
                ctx["available_slots"] = slots
                helper.set_booking_context(user_id, ctx)
                return helper.ask_booking_info(slots, conversation_key, history)

            # 5.e — Chỉ xác nhận khi đủ 3 trường: spa_name + service_name + slot
            if not (ctx.get("spa_name") and ctx.get("service_name") and ctx.get("slot")):
                helper.set_booking_context(user_id, ctx)
                return helper.finalize_reply("Mình cần **tên dịch vụ** và **thời gian** để giữ chỗ nhé.", conversation_key, history)

            # Nếu tin nhắn là “đồng ý” nhưng thiếu trường → bỏ qua xác nhận
            if is_confirm and not (ctx.get("spa_name") and ctx.get("service_name") and ctx.get("slot")):
                helper.set_booking_context(user_id, ctx)
                return helper.finalize_reply("Bạn vui lòng chọn **dịch vụ** và **thời gian** trước khi xác nhận nhé.", conversation_key, history)

            # 5.f — Hỏi xác nhận / hoặc xác nhận nếu user đã nói “đồng ý” sau khi ĐỦ thông tin
            filled, ctx, ask = helper.handle_booking_details(ctx, message)
            helper.set_booking_context(user_id, ctx)
            if not filled:
                return helper.finalize_reply(ask, conversation_key, history)

            # 5.g — Lưu + clean context
            confirmation = helper.confirm_booking(ctx)
            helper.add_appointment(user_id, ctx)
            helper.clear_booking_context(user_id)
            return helper.finalize_reply(confirmation, conversation_key, history)

        # ===== 6) Danh sách lịch hẹn (tổng) =====
        if helper.is_request_for_my_appointments(message):
            return helper.reply_my_appointments(user_id, conversation_key, history)

        # ===== 7) Giới thiệu dịch vụ cụ thể (không booking) =====
        exact = helper.find_exact_service_by_name(message, spa_services)
        if exact and not helper.is_booking_request(message):
            return helper.reply_service_detail(exact, conversation_key, history)

        # ===== 8) Fallback (GPT) =====
        return helper.reply_with_gpt_history(client, history, message, user_id)