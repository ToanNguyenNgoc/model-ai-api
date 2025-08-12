# -*- coding: utf-8 -*-
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Optional, Tuple


class ParseTimeText:
    """
    Parser tiếng Việt (tự nhiên) cho thời gian/Ngày giờ.
    Hỗ trợ ví dụ:
      - "12/08/2025 09:00", "12/8 lúc 9h", "12-8 14:30"
      - "2 giờ chiều nay", "9h kém 15 tối mai", "9 giờ rưỡi sáng thứ 6 tuần sau"
      - "thứ 3", "CN tuần sau", "ngày 5 lúc 14:00"
      - "2pm/2 am", "9h30", "tối nay", "trưa mai"
    Trả về datetime (naive, local) hoặc None nếu không bắt được.
    """

    # ---------- Public API ----------
    def parse(self, text: str, now: Optional[datetime] = None) -> Optional[datetime]:
        now = now or datetime.now()
        raw = (text or "").strip()
        norm = self._normalize(raw)

        # 1) các format số rõ ràng: dd/mm[/yyyy] + hh[:mm]
        dt = self._parse_compact_datetime(norm)
        if dt:
            return dt

        # 2) tách riêng date/time rồi ghép
        date_info = self._parse_explicit_date(raw, now) or self._parse_relative_date(norm, now)
        time_info = self._parse_time(raw, norm)

        if date_info or time_info:
            if date_info:
                y, mth, d, has_explicit_date = date_info
            else:
                y, mth, d, has_explicit_date = now.year, now.month, now.day, False

            if time_info:
                h, mm, has_explicit_time, _has_daypart = time_info
            else:
                h, mm, has_explicit_time = 9, 0, False

            try:
                dt = datetime(y, mth, d, h, mm, 0)
            except Exception:
                return None
            return self._clamp_next_day_if_past(dt, now, has_explicit_date)

        # 3) chỉ có giờ
        time_only = self._parse_time(raw, norm)
        if time_only:
            h, mm, has_explicit_time, _has_daypart = time_only
            try:
                dt = datetime(now.year, now.month, now.day, h, mm, 0)
            except Exception:
                return None
            return self._clamp_next_day_if_past(dt, now, False)

        return None

    # ---------- Internals ----------
    @staticmethod
    def _normalize(s: str) -> str:
        s = (s or "").casefold().strip()
        s = unicodedata.normalize("NFD", s)
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

        def fold_char(ch: str) -> str:
            if ch.isascii():
                return ch
            name = unicodedata.name(ch, "")
            if name.startswith("LATIN") and " LETTER " in name and " WITH " in name:
                base = name.split(" LETTER ", 1)[1].split(" WITH ", 1)[0]
                for c in base:
                    if c.isalpha():
                        return c.lower()
            if ch in ("đ", "Đ"):
                return "d"
            return ch

        s = "".join(fold_char(ch) for ch in s)
        s = re.sub(r"\s+", " ", s)
        return s

    @staticmethod
    def _clamp_next_day_if_past(dt: datetime, now: datetime, has_explicit_date: bool) -> datetime:
        # Nếu KHÔNG nêu ngày rõ ràng (chỉ giờ) mà đã quá giờ hôm nay → đẩy sang ngày mai
        if not has_explicit_date and dt < now:
            return dt + timedelta(days=1)
        return dt

    def _parse_compact_datetime(self, norm: str) -> Optional[datetime]:
        # dd/mm/yyyy hh[:mm]
        m = re.search(
            r"\b(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})\b\s*(?:luc|l|vao luc|vao)?\s*(\d{1,2})(?::(\d{2}))?\b",
            norm,
        )
        if m:
            d, mth, y, h, mm = m.groups()
            h = int(h); mm = int(mm) if mm else 0
            try:
                return datetime(int(y), int(mth), int(d), h, mm, 0)
            except Exception:
                return None

        # dd/mm (năm hiện tại) + hh[:mm]
        now = datetime.now()
        m = re.search(
            r"\b(\d{1,2})[\/\-](\d{1,2})\b\s*(?:\b(?:nam|năm)\s+(\d{4}))?\s*(?:luc|l|vao luc|vao)?\s*(\d{1,2})(?::(\d{2}))?\b",
            norm,
        )
        if m:
            d, mth, y_opt, h, mm = m.groups()
            y = int(y_opt) if y_opt else now.year
            h = int(h); mm = int(mm) if mm else 0
            try:
                return datetime(y, int(mth), int(d), h, mm, 0)
            except Exception:
                return None

        return None

    def _parse_explicit_date(self, raw: str, now: datetime) -> Optional[Tuple[int, int, int, bool]]:
        # dd/mm/yyyy
        m = re.search(r"\b(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})\b", raw)
        if m:
            d, mth, y = map(int, m.groups())
            return y, mth, d, True

        # dd/mm
        m = re.search(r"\b(\d{1,2})[\/\-](\d{1,2})\b", raw)
        if m:
            d, mth = map(int, m.groups())
            return now.year, mth, d, True

        # 'ngày/Ngay 12'
        norm = self._normalize(raw)
        m = re.search(r"\bngay\s+(\d{1,2})\b", norm)
        if m:
            d = int(m.group(1))
            y, mth = now.year, now.month
            try_dt = datetime(y, mth, d, 9, 0, 0)
            if try_dt < now:
                if mth == 12:
                    y, mth = y + 1, 1
                else:
                    mth += 1
            return y, mth, d, True

        return None

    def _parse_relative_date(self, text_norm: str, now: datetime) -> Optional[Tuple[int, int, int, bool]]:
        # hôm nay / nay
        if re.search(r"\bhom nay\b|\bnay\b", text_norm):
            return now.year, now.month, now.day, False

        # ngày mai / mai
        if re.search(r"\b(ngay )?mai\b", text_norm):
            dt = now + timedelta(days=1)
            return dt.year, dt.month, dt.day, False

        # mốt / ngày kia
        if re.search(r"\bmot\b|\bngay kia\b", text_norm):
            dt = now + timedelta(days=2)
            return dt.year, dt.month, dt.day, False

        # thứ trong tuần (+ tùy chọn tuần sau/tuần này)
        wd_map = {
            "thu 2": 0, "thu hai": 0,
            "thu 3": 1, "thu ba": 1,
            "thu 4": 2, "thu tu": 2,
            "thu 5": 3, "thu nam": 3,
            "thu 6": 4, "thu sau": 4,
            "thu 7": 5, "thu bay": 5,
            "chu nhat": 6, "cn": 6,
        }
        week_offset = 0
        if re.search(r"\btuan sau\b|\btuan toi\b", text_norm):
            week_offset = 7
        elif re.search(r"\btuan nay\b", text_norm):
            week_offset = 0

        for key, target_wd in wd_map.items():
            if re.search(rf"\b{key}\b", text_norm):
                base = now + timedelta(days=week_offset)
                days_ahead = (target_wd - base.weekday()) % 7
                dt = base + timedelta(days=days_ahead)
                return dt.year, dt.month, dt.day, False

        # buổi + 'nay/mai' (ví dụ "tối nay", "sáng mai")
        if re.search(r"\b(sang|trua|chieu|toi|dem|khuya)\s+(nay|hom nay)\b", text_norm):
            return now.year, now.month, now.day, False
        if re.search(r"\b(sang|trua|chieu|toi|dem|khuya)\s+mai\b", text_norm):
            dt = now + timedelta(days=1)
            return dt.year, dt.month, dt.day, False

        return None

    def _parse_time(self, raw: str, norm: str) -> Optional[Tuple[int, int, bool, bool]]:
        # am/pm flags
        am = bool(re.search(r"\bam\b", norm))
        pm = bool(re.search(r"\bpm\b", norm))

        # buổi
        daypart = None
        if re.search(r"\bsang\b", norm): daypart = "sang"
        elif re.search(r"\btrua\b", norm): daypart = "trua"
        elif re.search(r"\bchieu\b", norm): daypart = "chieu"
        elif re.search(r"\btoi\b", norm): daypart = "toi"
        elif re.search(r"\bdem\b", norm): daypart = "dem"
        elif re.search(r"\bkhuya\b", norm): daypart = "khuya"

        # hh:mm
        m = re.search(r"\b(\d{1,2}):(\d{2})\b", raw)
        if m:
            h, mnt = map(int, m.groups())
            if pm and 1 <= h <= 11: h += 12
            if am and h == 12: h = 0
            if daypart in ("trua", "chieu", "toi", "dem", "khuya") and h < 12:
                h += 12
            return h, mnt, True, bool(daypart)

        # 9h30 / 9g30 / 9 gio 30
        m = re.search(r"\b(\d{1,2})\s*(?:h|g|gio|giờ)\s*(\d{1,2})\b", norm)
        if m:
            h, mnt = map(int, m.groups())
            if pm and 1 <= h <= 11: h += 12
            if am and h == 12: h = 0
            if daypart in ("trua", "chieu", "toi", "dem", "khuya") and h < 12:
                h += 12
            return h, mnt, True, bool(daypart)

        # 9h / 9 giờ
        m = re.search(r"\b(\d{1,2})\s*(?:h|g|gio|giờ)\b", norm)
        if m:
            h = int(m.group(1)); mnt = 0
            # 'kém 15'
            m2 = re.search(r"\bkem\s+(\d{1,2})\b", norm)
            if m2:
                minus = int(m2.group(1))
                mnt = (60 - minus) % 60
                h = (h - 1) if minus > 0 else h
            # 'rưỡi'
            if re.search(r"\br\w*?i\b", norm):  # ruoi/rưởi
                mnt = 30
            if pm and 1 <= h <= 11: h += 12
            if am and h == 12: h = 0
            if daypart in ("trua", "chieu", "toi", "dem", "khuya") and h < 12:
                h += 12
            return h, mnt, True, bool(daypart)

        # 2 pm / 2 a.m.
        m = re.search(r"\b(\d{1,2})\s*p\.?m\.?\b", norm)
        if m:
            h = int(m.group(1))
            if 1 <= h <= 11: h += 12
            return h, 0, True, False

        m = re.search(r"\b(\d{1,2})\s*a\.?m\.?\b", norm)
        if m:
            h = int(m.group(1))
            if h == 12: h = 0
            return h, 0, True, False

        # chỉ buổi
        if daypart:
            defaults = {"sang": 9, "trua": 12, "chieu": 15, "toi": 19, "dem": 22, "khuya": 23}
            return defaults[daypart], (30 if daypart == "khuya" else 0), False, True

        return None
