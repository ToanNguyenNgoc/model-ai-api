# -*- coding: utf-8 -*-
from apps.utils.spa_services import spa_services

def try_handle_service_list(tv, client, message, user_id, conversation_key, history, ctx):
    if not tv.is_request_for_service_list(message):
        return False

    spa_names = list(spa_services.keys())
    spa_name = tv.detect_spa_in_message(message, spa_names)

    # Ưu tiên lấy spa từ: câu nói > ctx.spa_name > last_spa_focus > last_spa_list
    target_spa = spa_name or ctx.get("spa_name") or tv.cache.get(f"{conversation_key}:last_spa_focus")
    if target_spa:
        if ctx.get("active"):
            tv.clear_booking_context(user_id)
        tv.reply_service_list(target_spa, spa_services, conversation_key, history)
        return True

    last_list = tv.get_last_spa_list(conversation_key)
    if last_list:
        picked = tv.resolve_spa_selection_from_message(message, last_list)
        if picked:
            if ctx.get("active"):
                tv.clear_booking_context(user_id)
            tv.reply_service_list(picked, spa_services, conversation_key, history)
            return True
        if ctx.get("active"):
            tv.clear_booking_context(user_id)
        tv.reply_choose_spa_from_last_list(conversation_key, history, note="để xem danh sách dịch vụ")
        return True

    if ctx.get("active"):
        tv.clear_booking_context(user_id)
    tv.finalize_reply("Bạn muốn xem **danh sách dịch vụ** của **spa nào** ạ?", conversation_key, history)
    return True
