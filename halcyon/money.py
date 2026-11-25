"""Rupee amounts: strict parsing of untrusted input and Indian-style formatting."""
import math
import re

MAX_PAYMENT = 1_000_000_000
_AMOUNT_RE = re.compile(r"^\d+(\.\d{1,2})?$")


def parse_amount(value) -> float | None:
    """Return a positive rupee amount, or None if the value isn't one.

    Accepts 4200, 4200.0, "4200", "₹4,200", "Rs. 4200". Rejects booleans, zero,
    negatives, NaN/inf, more than two decimals and absurdly large values.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    elif isinstance(value, str):
        s = re.sub(r"^(₹|rs\.?|inr)\s*", "", value.strip(), flags=re.I).replace(",", "").strip()
        if not _AMOUNT_RE.match(s):
            return None
        v = float(s)
    else:
        return None
    if not math.isfinite(v) or v <= 0 or v > MAX_PAYMENT or round(v, 2) != v:
        return None
    return v


def inr(amount) -> str:
    """Format like ₹1,20,000 or ₹4,200.50."""
    if amount is None:
        return "₹?"
    neg = amount < 0
    amount = abs(float(amount))
    whole = int(amount)
    paise = round((amount - whole) * 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = head + "," + tail
    out = "₹" + s + (f".{paise:02d}" if paise else "")
    return "-" + out if neg else out
