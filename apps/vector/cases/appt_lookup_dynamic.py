# -*- coding: utf-8 -*-

def try_handle_appt_lookup_dynamic(tv, client, message, user_id, conversation_key, history, ctx):
    if not tv.is_appointments_lookup_intent(message):
        return False
    pr = tv.parse_appointment_range(message)
    if pr:
        start, end, title = pr
        tv.reply_my_appointments_in_range(user_id, start, end, title, conversation_key, history)
        return True
    # không nhận ra khoảng → fallback liệt kê tất cả
    tv.reply_my_appointments(user_id, conversation_key, history)
    return True
