import re
import unicodedata

_OVERRIDE = re.compile(
    r"(?:игнорируй|забудь|отмени|нарушь|ignore|disregard|override).{0,80}"
    r"(?:инструкц|правил|промпт|instructions|rules|prompt)"
    r"|(?:покажи|раскрой|выведи|напечатай|reveal|show|print).{0,60}"
    r"(?:системн.{0,20}промпт|секрет|парол|api[_ -]?key|system prompt|secret|password)"
    r"|(?:выполни|запусти|run|execute|вызови).{0,50}"
    r"(?:\bsql\b|команд|оболоч|shell|\bbash\b|delete_product|create_order|update_price)"
    r"|(?:измени|обнови|удали|создай|оплати).{0,36}"
    r"(?:цену|каталог|остатки|заказ|платеж)"
)


def suspicious_instruction(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    visible = (character for character in normalized if unicodedata.category(character) != "Cf")
    return _OVERRIDE.search(" ".join("".join(visible).split())) is not None
