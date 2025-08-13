# -*- coding: utf-8 -*-
from apps.utils.spa_services import spa_services

def try_handle_service_detail(tv, client, message, user_id, conversation_key, history, ctx):
    # Chỉ khi KHÔNG có ý định đặt hẹn
    if tv.is_booking_request(message):
        return False
    exact = tv.find_exact_service_by_name(message, spa_services)
    if exact:
        tv.reply_service_detail(exact, conversation_key, history)
        return True
    return False
