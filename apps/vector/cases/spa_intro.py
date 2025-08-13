# -*- coding: utf-8 -*-
from apps.utils.spa_locations import spa_locations
from apps.utils.spa_services import spa_services

def try_handle_spa_intro(tv, client, message, user_id, conversation_key, history, ctx):
    spa_names = list(spa_services.keys())
    spa_name = tv.detect_spa_in_message(message, spa_names)
    if spa_name and tv.is_request_for_spa_intro(message, spa_name):
        tv.reply_spa_intro(spa_name, spa_locations, conversation_key, history)
        return True
    return False
