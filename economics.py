from decimal import Decimal
from models import BROKERS, REG_BPS, ZERO, Rejected, D
from utils import bps, money

def route_for(quantity, limit_price, asset_class):
    notional = D(str(quantity)) * D(str(limit_price))
    best_name, best_charge = None, None
    for name in sorted(BROKERS):
        b = BROKERS[name]
        if asset_class not in b["classes"]:
            continue
        charge = max(bps(notional, b["bkg"]), b["min"]) + bps(notional, b["cus"])
        if best_charge is None or charge < best_charge:
            best_name, best_charge = name, charge
    if best_name is None:
        raise Rejected("no broker")
    return best_name

def fill_economics(principal, broker, partner_rate):
    b = BROKERS[broker]
    p = D(str(principal))

    brokerage = max(bps(p, b["bkg"]), b["min"])
    custody = bps(p, b["cus"])
    reg = bps(p, REG_BPS)

    broker_cost = bps(p, b["bcost"]) + b["ticket"]
    custody_cost = bps(p, b["ccost"])

    margin = (brokerage + custody) - (broker_cost + custody_cost)
    partner = money(D(str(partner_rate)) * margin) if margin > 0 else ZERO

    return {"brokerage": brokerage, "custody": custody, "reg": reg,
            "broker_cost": broker_cost, "custody_cost": custody_cost,
            "partner": partner, "payable": b["payable"]}
