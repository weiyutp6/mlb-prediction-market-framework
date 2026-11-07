import json


def parse_field(obj, *attr_names):
    """Try multiple attribute/key names on obj; return first non-None value found."""
    for name in attr_names:
        val = getattr(obj, name, None)
        if val is None:
            try:
                val = obj[name]
            except Exception:
                pass
        if val is not None:
            return val
    return None


def parse_list_field(raw) -> list:
    """Coerce a JSON-encoded string or a native list to list. Returns [] on failure."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


def parse_outcomes(raw) -> list[str]:
    return [str(x) for x in parse_list_field(raw)]


def parse_prices(raw) -> list[float]:
    return [float(x) for x in parse_list_field(raw)]


def parse_token_ids(raw) -> list[str]:
    return [str(x) for x in parse_list_field(raw)]
