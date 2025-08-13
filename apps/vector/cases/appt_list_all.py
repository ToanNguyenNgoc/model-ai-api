# -*- coding: utf-8 -*-

def try_handle_appt_list_all(tv, client, message, user_id, conversation_key, history, ctx):
    if tv.is_request_for_my_appointments(message):
        tv.reply_my_appointments(user_id, conversation_key, history)
        return True
    return False
