# -*- coding: utf-8 -*-
from apps.vector.cases.spa_by_city import try_handle_spa_by_city
from apps.vector.cases.spa_intro import try_handle_spa_intro
from apps.vector.cases.service_list import try_handle_service_list
from apps.vector.cases.appt_lookup_dynamic import try_handle_appt_lookup_dynamic
from apps.vector.cases.appt_list_all import try_handle_appt_list_all
from apps.vector.cases.booking import try_handle_booking
from apps.vector.cases.service_detail import try_handle_service_detail
from apps.vector.cases.skincare_gpt import try_handle_skincare_or_fallback


CASES_IN_ORDER = [
    # 1) Danh sách spa theo vị trí (ưu tiên cao, cắt booking treo)
    try_handle_spa_by_city,
    # 2) Tên spa → giới thiệu spa
    try_handle_spa_intro,
    # 3) Danh sách dịch vụ của 1 spa
    try_handle_service_list,
    # 3c) Tra cứu lịch hẹn theo khoảng thời gian (hôm nay/mai/tuần... dynamic)
    try_handle_appt_lookup_dynamic,
    # 3d) Xem tất cả lịch hẹn của tôi
    try_handle_appt_list_all,
    # 4) Booking (ưu tiên hơn service detail)
    try_handle_booking,
    # 5) Giới thiệu dịch vụ cụ thể (KHI KHÔNG có ý định đặt hẹn)
    try_handle_service_detail,
    # 6 & 7) Skincare bằng GPT hoặc fallback GPT
    try_handle_skincare_or_fallback,
]


def route_message(tv, client, message, user_id, conversation_key, history):
    """
    Chạy lần lượt từng case. Case nào xử lý được thì kết thúc.
    """
    ctx = tv.get_booking_context(user_id)
    for case in CASES_IN_ORDER:
        handled = case(tv, client, message, user_id, conversation_key, history, ctx)
        if handled:
            return True
    return False
