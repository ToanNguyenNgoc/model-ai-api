# -*- coding: utf-8 -*-

def try_handle_skincare_or_fallback(tv, client, message, user_id, conversation_key, history, ctx):
    if tv.is_general_skin_question_gpt(message, client):
        tv.reply_with_gpt_history(client, history, message, user_id)
        return True
    # Fallback GPT
    tv.reply_with_gpt_history(client, history, message, user_id)
    return True
