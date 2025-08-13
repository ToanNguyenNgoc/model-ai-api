# -*- coding: utf-8 -*-
from apps.utils.spa_services import spa_services

def try_handle_booking(tv, client, message, user_id, conversation_key, history, ctx):
    spa_names = list(spa_services.keys())
    spa_name_from_msg = tv.detect_spa_in_message(message, spa_names)

    # Reset khi “đặt thêm”
    if tv.is_additional_booking(message) and ctx.get("active"):
        tv.clear_booking_context(user_id)
        ctx = {"active": False}

    if not (tv.is_booking_request(message) or ctx.get("active")):
        return False

    # 4.a0: Nếu vòng trước gợi ý nhiều dịch vụ → đọc lựa chọn ở vòng này
    if ctx.get("service_candidates") and not ctx.get("service_name"):
        chosen = tv.resolve_service_selection_from_message(message, ctx["service_candidates"])
        if chosen:
            ctx["service_name"] = chosen
            ctx.pop("service_candidates", None)

    # 4.a: Lấy DỊCH VỤ (từ message / 'dịch vụ này' / khớp mơ hồ)
    if not ctx.get("service_name"):
        if tv.is_referring_prev_service(message):
            last = tv.cache.get(f"{conversation_key}:last_context")
            if last:
                ctx["service_name"] = last.get("service_name")
                if not ctx.get("spa_name"):
                    ctx["spa_name"] = last.get("spa_name")

        if not ctx.get("service_name"):
            mentioned = tv.find_services_in_text(message, spa_services)
            if mentioned:
                unique = sorted({m["service"]["name"] for m in mentioned})
                if len(unique) == 1:
                    ctx["service_name"] = unique[0]
                else:
                    ctx["service_candidates"] = unique
                    tv.set_booking_context(user_id, {**ctx, "active": True})
                    tv.reply_choose_service(unique, conversation_key, history)
                    return True

    # 4.b: Nếu user đã nói giờ → bắt luôn, không gợi ý slot
    if not ctx.get("slot"):
        desired_dt = tv.parse_datetime_from_message(message)
        if desired_dt:
            ctx["slot"] = {"label": desired_dt.strftime("%d/%m/%Y %H:%M"), "iso": desired_dt.isoformat()}

    # 4.c: Xác định SPA (câu nói > last_spa_focus > theo dịch vụ)
    if not ctx.get("spa_name"):
        if spa_name_from_msg:
            ctx["spa_name"] = spa_name_from_msg
        else:
            last_focus = tv.cache.get(f"{conversation_key}:last_spa_focus")
            if last_focus:
                ctx["spa_name"] = last_focus
            elif ctx.get("service_name"):
                spas_for_service = tv.get_spas_by_service_name(ctx["service_name"])
                tv.set_booking_context(user_id, {**ctx, "active": True})
                if len(spas_for_service) == 0:
                    tv.finalize_reply("Dịch vụ này hiện chưa có spa nào trong hệ thống. Bạn muốn chọn dịch vụ khác không?",
                                      conversation_key, history)
                    return True
                elif len(spas_for_service) == 1:
                    ctx["spa_name"] = spas_for_service[0]["name"]
                else:
                    slot_label = ctx["slot"]["label"] if ctx.get("slot") else None
                    tv.reply_choose_spa_for_service(ctx["service_name"], spas_for_service,
                                                    conversation_key, history, slot_label=slot_label)
                    return True
            else:
                tv.set_booking_context(user_id, {**ctx, "active": True})
                tv.finalize_reply("Bạn muốn đặt **dịch vụ** nào và tại **spa** nào ạ? (Bạn có thể trả lời: 'tên dịch vụ + tên spa')",
                                  conversation_key, history)
                return True

    # ✳️ Nếu đã biết SPA nhưng CHƯA có dịch vụ → hỏi chọn dịch vụ của spa đó
    if ctx.get("spa_name") and not ctx.get("service_name"):
        service_list = [s["name"] for s in spa_services.get(ctx["spa_name"], [])]
        ctx["service_candidates"] = service_list
        tv.set_booking_context(user_id, {**ctx, "active": True})
        tv.reply_choose_service_for_spa(ctx["spa_name"], service_list, conversation_key, history)
        return True

    # 4.d: Nếu CHƯA có slot → gợi ý slot
    if not ctx.get("slot"):
        slots = tv.get_available_slots(ctx["spa_name"])
        ctx["available_slots"] = slots
        tv.set_booking_context(user_id, {**ctx, "active": True})
        tv.ask_booking_info(slots, conversation_key, history)
        return True

    # 4.e: Thu thập thông tin & xác nhận
    filled, ctx, ask = tv.handle_booking_details(ctx, message)
    tv.set_booking_context(user_id, {**ctx, "active": True})
    if not filled:
        tv.finalize_reply(ask, conversation_key, history)
        return True

    # 4.f: Lưu + sạch context + trả kết quả
    confirmation = tv.confirm_booking(ctx)
    tv.add_appointment(user_id, ctx)
    tv.clear_booking_context(user_id)  # CLEAN lịch trước đó sau khi đặt THÀNH CÔNG
    tv.finalize_reply(confirmation, conversation_key, history)
    return True
