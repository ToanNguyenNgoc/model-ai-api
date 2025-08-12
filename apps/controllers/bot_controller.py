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
        # Input
        message = self.get_request()['message']
        user_id = self.get_request()['user_id']
        conversation_key = f"chat:{user_id}"
        history = cache.get(conversation_key) or []
        history.append({"role": "user", "content": message})

        helper = TrainingVector()
        client = OpenAI(api_key=os.getenv("A_SECRET_KEY"))
        ctx = helper.get_booking_context(user_id)

        # Nếu hỏi DS spa theo vị trí → ưu tiên & tắt booking đang treo
        if helper.is_request_for_spa_list(message) and ctx.get("active"):
            helper.clear_booking_context(user_id); ctx = {"active": False}

        # ===== 1) Danh sách spa theo vị trí =====
        city_keywords = helper.extract_city_keywords(spa_locations)
        city = helper.extract_city_from_message(message, city_keywords)
        if city and helper.is_request_for_spa_list(message):
            matched_spas = helper.find_spas_by_city(spa_locations, city)
            return helper.reply_spa_list(city, matched_spas, conversation_key, history)

        # ===== 2) Tên spa → giới thiệu spa =====
        spa_names = list(spa_services.keys())
        spa_name = helper.detect_spa_in_message(message, spa_names)
        if spa_name and helper.is_request_for_spa_intro(message, spa_name):
            return helper.reply_spa_intro(spa_name, spa_locations, conversation_key, history)

        # ===== 3) DANH SÁCH DỊCH VỤ (ƯU TIÊN HƠN BOOKING ĐANG TREO) =====
        if helper.is_request_for_service_list(message):
            # Ưu tiên lấy spa từ: câu nói > ctx.spa_name > last_spa_focus > last_spa_list
            target_spa = spa_name or ctx.get("spa_name") or cache.get(f"{conversation_key}:last_spa_focus")
            if target_spa:
                # tuỳ chọn: tắt booking treo để tránh show slot khi user đang xem dịch vụ
                if ctx.get("active"):
                    helper.clear_booking_context(user_id)
                return helper.reply_service_list(target_spa, spa_services, conversation_key, history)

            last_list = helper.get_last_spa_list(conversation_key)
            if last_list:
                picked = helper.resolve_spa_selection_from_message(message, last_list)
                if picked:
                    if ctx.get("active"):
                        helper.clear_booking_context(user_id)
                    return helper.reply_service_list(picked, spa_services, conversation_key, history)
                if ctx.get("active"):
                    helper.clear_booking_context(user_id)
                return helper.reply_choose_spa_from_last_list(conversation_key, history, note="để xem danh sách dịch vụ")

            if ctx.get("active"):
                helper.clear_booking_context(user_id)
            return helper.finalize_reply("Bạn muốn xem **danh sách dịch vụ** của **spa nào** ạ?", conversation_key, history)
        # ===== 3) Xem danh sách lịch hẹn của tôi =====
        if helper.is_request_for_my_appointments(message):
            # không cần clear booking; chỉ liệt kê
            return helper.reply_my_appointments(user_id, conversation_key, history)
        # ===== 4) (ƯU TIÊN) BOOKING =====
        if helper.is_booking_request(message) or ctx.get("active"):
            # 4.a0: Nếu vòng trước đã gợi ý nhiều dịch vụ → đọc lựa chọn ở vòng này
            if ctx.get("service_candidates") and not ctx.get("service_name"):
                chosen = helper.resolve_service_selection_from_message(message, ctx["service_candidates"])
                if chosen:
                    ctx["service_name"] = chosen
                    ctx.pop("service_candidates", None)

            # 4.a: Lấy DỊCH VỤ (từ message / tham chiếu 'dịch vụ này' / khớp mơ hồ)
            if not ctx.get("service_name"):
                if helper.is_referring_prev_service(message):
                    last = cache.get(f"{conversation_key}:last_context")
                    if last:
                        ctx["service_name"] = last.get("service_name")
                        if not ctx.get("spa_name"):
                            ctx["spa_name"] = last.get("spa_name")

                if not ctx.get("service_name"):
                    mentioned = helper.find_services_in_text(message, spa_services)
                    if mentioned:
                        unique = sorted({m["service"]["name"] for m in mentioned})
                        if len(unique) == 1:
                            ctx["service_name"] = unique[0]
                        else:
                            ctx["service_candidates"] = unique
                            helper.set_booking_context(user_id, {**ctx, "active": True})
                            return helper.reply_choose_service(unique, conversation_key, history)

            # 4.b: Bắt THỜI GIAN nếu user đã nêu (không show slot nếu đã có)
            if not ctx.get("slot"):
                desired_dt = helper.parse_datetime_from_message(message)
                if desired_dt:
                    ctx["slot"] = {"label": desired_dt.strftime("%d/%m/%Y %H:%M"), "iso": desired_dt.isoformat()}

            # 4.c: Xác định SPA (từ message > last_spa_focus > theo dịch vụ)
            if not ctx.get("spa_name"):
                spa_from_msg = spa_name or helper.detect_spa_in_message(message, spa_names)
                if spa_from_msg:
                    ctx["spa_name"] = spa_from_msg
                else:
                    last_focus = cache.get(f"{conversation_key}:last_spa_focus")
                    if last_focus:
                        ctx["spa_name"] = last_focus
                    elif ctx.get("service_name"):
                        spas_for_service = helper.get_spas_by_service_name(ctx["service_name"])
                        helper.set_booking_context(user_id, {**ctx, "active": True})
                        if len(spas_for_service) == 0:
                            return helper.finalize_reply(
                                "Dịch vụ này hiện chưa có spa nào trong hệ thống. Bạn muốn chọn dịch vụ khác không?",
                                conversation_key, history
                            )
                        elif len(spas_for_service) == 1:
                            ctx["spa_name"] = spas_for_service[0]["name"]
                        else:
                            slot_label = ctx["slot"]["label"] if ctx.get("slot") else None
                            return helper.reply_choose_spa_for_service(
                                ctx["service_name"], spas_for_service, conversation_key, history, slot_label=slot_label
                            )
                    else:
                        helper.set_booking_context(user_id, {**ctx, "active": True})
                        return helper.finalize_reply(
                            "Bạn muốn đặt **dịch vụ** nào và tại **spa** nào ạ? (Bạn có thể trả lời: 'tên dịch vụ + tên spa')",
                            conversation_key, history
                        )

            # ✳️ MỚI: Nếu đã biết SPA nhưng CHƯA có dịch vụ → hỏi chọn dịch vụ của spa đó
            if ctx.get("spa_name") and not ctx.get("service_name"):
                service_list = [s["name"] for s in spa_services.get(ctx["spa_name"], [])]
                ctx["service_candidates"] = service_list
                helper.set_booking_context(user_id, {**ctx, "active": True})
                return helper.reply_choose_service_for_spa(ctx["spa_name"], service_list, conversation_key, history)

            # 4.d: Nếu CHƯA có slot → gợi ý slot
            if not ctx.get("slot"):
                slots = helper.get_available_slots(ctx["spa_name"])
                ctx["available_slots"] = slots
                helper.set_booking_context(user_id, {**ctx, "active": True})
                return helper.ask_booking_info(slots, conversation_key, history)

            # 4.e: Thu thập tên / SĐT / xác nhận
            filled, ctx, ask = helper.handle_booking_details(ctx, message)
            helper.set_booking_context(user_id, {**ctx, "active": True})
            if not filled:
                return helper.finalize_reply(ask, conversation_key, history)

            # 4.f: Xác nhận đặt lịch
            confirmation = helper.confirm_booking(ctx)
            helper.add_appointment(user_id, ctx)
            helper.clear_booking_context(user_id)
            return helper.finalize_reply(confirmation, conversation_key, history)

        # ===== 5) Giới thiệu dịch vụ cụ thể (chỉ khi KHÔNG booking) =====
        if not helper.is_booking_request(message):
            exact = helper.find_exact_service_by_name(message, spa_services)
            if exact:
                return helper.reply_service_detail(exact, conversation_key, history)

        # ===== 6) Skincare chung =====
        if helper.is_general_skin_question_gpt(message, client):
            return helper.reply_with_gpt_history(client, history, message, user_id)

        # ===== 7) Fallback GPT =====
        return helper.reply_with_gpt_history(client, history, message, user_id)