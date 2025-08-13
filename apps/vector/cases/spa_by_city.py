# -*- coding: utf-8 -*-
from apps.utils.spa_locations import spa_locations

def try_handle_spa_by_city(tv, client, message, user_id, conversation_key, history, ctx):
    # Nếu user hỏi DS spa theo vị trí → ưu tiên flow này & tắt booking đang treo
    if tv.is_request_for_spa_list(message):
        if ctx.get("active"):
            tv.clear_booking_context(user_id)
        city_keywords = tv.extract_city_keywords(spa_locations)
        city = tv.extract_city_from_message(message, city_keywords)
        if city:
            matched_spas = tv.find_spas_by_city(spa_locations, city)
            tv.reply_spa_list(city, matched_spas, conversation_key, history)
            return True
    return False
