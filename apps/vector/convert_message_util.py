import re
import unicodedata

class ConvertMessageUtils:
  def _normalize(s: str) -> str:
        s = (s or "").casefold().strip()
        s = unicodedata.normalize("NFD", s)
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
        # dynamic fold: LATIN ... LETTER X WITH ... -> x
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