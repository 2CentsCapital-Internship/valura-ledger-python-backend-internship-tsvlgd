from dataclasses import dataclass, field
from decimal import Decimal

D = Decimal
ZERO = D("0.00")
REG_BPS = D(8)

BROKERS = {
    "BRK-A": {"classes": ("equity", "etf"), "bkg": D(20), "cus": D(4),
              "bcost": D(9), "ccost": D(2), "min": D("1.00"),
              "ticket": D("0.35"), "payable": "2411"},
    "BRK-B": {"classes": ("equity", "bond"), "bkg": D(15), "cus": D(5),
              "bcost": D(8), "ccost": D(3), "min": D("2.50"),
              "ticket": D("3.00"), "payable": "2412"},
    "BRK-C": {"classes": ("etf", "bond"), "bkg": D(25), "cus": D(3),
              "bcost": D(12), "ccost": D(1), "min": D("0.50"),
              "ticket": D("0.20"), "payable": "2413"},
}

LOT_EVENTS = {"order_filled", "order_partially_filled", "dividend_reinvested",
              "stock_split", "symbol_change"}

class Rejected(Exception):
    """Event refused on domain rules."""

@dataclass
class Lot:
    quantity: Decimal
    total_cost: Decimal

@dataclass
class OrderState:
    order_id: str
    customer_id: str
    side: str
    symbol: str
    asset_class: str
    quantity: Decimal
    limit_price: Decimal
    est_charges: Decimal
    initial_hold: Decimal
    cash_hold: Decimal
    route: str
    status: str = "open"
    filled_qty: Decimal = field(default_factory=lambda: ZERO)

@dataclass
class TradeInfo:
    customer_id: str
    side: str
    principal: Decimal
    status: str = "open"
