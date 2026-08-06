from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from models import Rejected, ZERO, D

def money(x) -> Decimal:
    return D(str(x)).quantize(D("0.01"), rounding=ROUND_HALF_UP)

def shares(x) -> Decimal:
    return D(str(x)).quantize(D("0.000001"), rounding=ROUND_HALF_UP)

def bps(amount, n) -> Decimal:
    return money(D(str(amount)) * D(str(n)) / D(10000))

def money_str(x) -> str:
    return format(money(x), "f")

def share_str(x) -> str:
    v = shares(x).normalize()
    return format(v, "f")

def amount_of(payload, key) -> Decimal:
    try:
        return money(payload[key])
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
        raise Rejected(f"bad {key}")

def qty_of(payload, key) -> Decimal:
    try:
        return shares(payload[key])
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
        raise Rejected(f"bad {key}")

def nonzero(legs) -> list:
    return [l for l in legs if D(l["debit"]) or D(l["credit"])]

def leg(account: str, customer_id: str, debit=ZERO, credit=ZERO) -> dict:
    return {"account": account, "customer_id": customer_id,
            "debit": money_str(debit), "credit": money_str(credit)}
