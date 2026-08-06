"""Double-entry book of record for the Ledger Arena stream."""
from __future__ import annotations

from collections import defaultdict, deque
from decimal import Decimal

from models import D, ZERO, LOT_EVENTS, BROKERS, Rejected, Lot, OrderState, TradeInfo
from utils import money, shares, money_str, share_str, amount_of, qty_of, nonzero, leg
from economics import route_for, fill_economics

class Book:
    def __init__(self) -> None:
        self.balances: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
        self.touched: set[str] = set()
        self.seen: set[str] = set()

        self.journal: list[dict] = []
        self.legs_by_event: dict[str, list] = {}
        self.posted: set[str] = set()
        self.reversed_events: set[str] = set()

        self.orders: dict[str, OrderState] = {}
        self.trades: dict[str, TradeInfo] = {}
        self.lots: dict[tuple[str, str], deque] = defaultdict(deque)

        self.fee_amounts: dict[str, tuple[str, Decimal]] = {}
        self.refunded_fees: set[str] = set()
        self.withdrawal_amounts: dict[str, tuple[str, Decimal, bool]] = {}
        self.early_fills: dict[str, Decimal] = defaultdict(lambda: ZERO)

        self.todo: dict[str, int] = defaultdict(int)
        self.errors: list[tuple] = []
        self.warnings: list[dict] = []

    def apply(self, ev: dict) -> list[dict]:
        eid = ev.get("event_id")
        if eid is None or eid in self.seen:
            return []
        self.seen.add(eid)
        self.journal.append(ev)

        try:
            payload = ev["payload"]
            handler = getattr(self, "on_" + ev["type"], None)
            if handler is None:
                self.todo[ev["type"]] += 1
                return []
            legs = nonzero(handler(payload, ev) or [])
        except Rejected:
            return []
        except Exception as exc:
            self.errors.append((eid, ev["type"], repr(exc)))
            return []

        self._post(legs)
        self.legs_by_event[eid] = legs
        self.posted.add(eid)
        return legs

    def _post(self, legs: list[dict]) -> None:
        dr = sum((D(l["debit"]) for l in legs), ZERO)
        cr = sum((D(l["credit"]) for l in legs), ZERO)
        if dr != cr:
            raise Exception(f"unbalanced: dr {dr} cr {cr}")
        for l in legs:
            self.balances[(l["customer_id"], l["account"])] += (
                D(l["debit"]) - D(l["credit"]))
            self.touched.add(l["account"])

    def payable_balance(self, customer_id, account) -> Decimal:
        return -self.balances[(customer_id, account)]

    # -------------------------------------------------------------------
    # Cash
    # -------------------------------------------------------------------

    def on_deposit(self, p, ev):
        amt = amount_of(p, "amount")
        cid = p["customer_id"]
        return [leg("1100", cid, debit=amt), leg("2010", cid, credit=amt)]

    def on_fee_charged(self, p, ev):
        amt = amount_of(p, "amount")
        cid = p["customer_id"]
        self.fee_amounts[ev["event_id"]] = (cid, amt)
        return [leg("2010", cid, debit=amt), leg("1100", cid, credit=amt)]

    def on_fee_refund(self, p, ev):
        src = p["refunds_source_id"]
        original = self.fee_amounts.get(src)
        if original is None or src in self.refunded_fees:
            raise Rejected("unknown or already refunded fee")
        self.refunded_fees.add(src)
        cid = p.get("customer_id") or original[0]
        amt = original[1]
        return [leg("1100", cid, debit=amt), leg("2010", cid, credit=amt)]

    def on_interest_credited(self, p, ev):
        gross = amount_of(p, "gross_amount")
        share = amount_of(p, "customer_share")
        if share > gross:
            raise Rejected("customer share exceeds gross")
        cid = p["customer_id"]
        return [leg("1100", cid, debit=gross),
                leg("2010", cid, credit=share),
                leg("4200", cid, credit=gross - share)]

    def on_transfer_between_customers(self, p, ev):
        amt = amount_of(p, "amount")
        return [leg("2010", p["from_customer_id"], debit=amt),
                leg("2010", p["to_customer_id"], credit=amt)]

    def on_fx_deposit(self, p, ev):
        at_market = amount_of(p, "usd_at_market_rate")
        at_customer = amount_of(p, "usd_at_customer_rate")
        if at_customer > at_market:
            raise Rejected("negative spread")
        cid = p["customer_id"]
        return [leg("1100", cid, debit=at_market),
                leg("2010", cid, credit=at_customer),
                leg("4100", cid, credit=at_market - at_customer)]

    def on_withdrawal_requested(self, p, ev):
        amt = amount_of(p, "amount")
        cid = p["customer_id"]
        self.withdrawal_amounts[p["withdrawal_id"]] = (cid, amt, True)
        return [leg("2010", cid, debit=amt), leg("2300", cid, credit=amt)]

    def _close_withdrawal(self, wid):
        w = self.withdrawal_amounts.get(wid)
        if w is None or not w[2]:
            raise Rejected("unknown or closed withdrawal")
        self.withdrawal_amounts[wid] = (w[0], w[1], False)
        return w

    def on_withdrawal_settled(self, p, ev):
        cid, amt, _ = self._close_withdrawal(p["withdrawal_id"])
        return [leg("2300", cid, debit=amt), leg("1100", cid, credit=amt)]

    def on_withdrawal_rejected(self, p, ev):
        cid, amt, _ = self._close_withdrawal(p["withdrawal_id"])
        return [leg("2300", cid, debit=amt), leg("2010", cid, credit=amt)]

    # -------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------

    def on_order_placed(self, p, ev):
        oid = p["order_id"]
        q = qty_of(p, "quantity")
        price = amount_of(p, "limit_price")
        ac = p.get("asset_class", "equity")
        side = p["side"]
        broker = route_for(q, price, ac)

        if side == "buy":
            est = amount_of(p, "est_charges") if "est_charges" in p else money(p.get("est_commission", "0"))
            hold = money(q * price + est)
        else:
            est = ZERO
            hold = ZERO

        order = OrderState(
            order_id=oid, customer_id=p["customer_id"], side=side, symbol=p["symbol"],
            asset_class=ac, quantity=q, limit_price=price,
            est_charges=est, initial_hold=hold, cash_hold=hold, route=broker,
        )

        already = self.early_fills.pop(oid, ZERO)
        if already > ZERO:
            order.filled_qty = already
            self._release_hold(order, already)

        self.orders[oid] = order
        return []

    def _release_hold(self, order: OrderState, fill_qty: Decimal):
        if order.cash_hold > ZERO:
            unfilled = order.quantity - order.filled_qty
            if unfilled > ZERO:
                released = money(order.cash_hold * fill_qty / unfilled)
                order.cash_hold = max(ZERO, money(order.cash_hold - released))

    def on_order_partially_filled(self, p, ev):
        return self._fill(p, ev, final=False)

    def on_order_filled(self, p, ev):
        return self._fill(p, ev, final=True)

    def _fill(self, p, ev, final: bool):
        cid = p["customer_id"]
        symbol = p["symbol"]
        side = p["side"]
        oid = p["order_id"]
        broker = p["broker"]
        trade_id = p.get("trade_id")

        if broker not in BROKERS:
            raise Rejected("unknown broker")

        if trade_id and trade_id in self.trades:
            raise Rejected("duplicate trade_id")

        quantity = qty_of(p, "quantity")
        principal = amount_of(p, "principal")
        partner_rate = D(str(p.get("partner_rate", 0)))
        e = fill_economics(principal, broker, partner_rate)

        if side == "buy":
            legs = self._buy_legs(cid, principal, e)
            self.lots[(cid, symbol)].append(Lot(quantity, principal))
        else:
            cost = self._relieve(cid, symbol, quantity)
            legs = self._sell_legs(cid, principal, cost, e)

        if trade_id:
            self.trades[trade_id] = TradeInfo(cid, side, principal)

        order = self.orders.get(oid)
        if order is None:
            self.early_fills[oid] += quantity
        else:
            if final:
                order.cash_hold = ZERO
                order.status = "closed"
            else:
                self._release_hold(order, quantity)
            order.filled_qty += quantity
        return legs

    def _buy_legs(self, cid, principal, e):
        charged = principal + e["brokerage"] + e["custody"] + e["reg"]
        return [
            leg("2010", cid, debit=charged),
            leg("1200", cid, debit=principal),
            leg("5000", cid, debit=e["broker_cost"]),
            leg("5010", cid, debit=e["custody_cost"]),
            leg("5100", cid, debit=e["partner"]),
            leg("2350", cid, credit=principal),
            leg("2100", cid, credit=principal),
            leg("4000", cid, credit=e["brokerage"]),
            leg("4010", cid, credit=e["custody"]),
            leg("2400", cid, credit=e["reg"]),
            leg(e["payable"], cid, credit=e["broker_cost"]),
            leg("2420", cid, credit=e["custody_cost"]),
            leg("2430", cid, credit=e["partner"]),
        ]

    def _sell_legs(self, cid, principal, cost, e):
        net = principal - e["brokerage"] - e["custody"] - e["reg"]
        return [
            leg("1150", cid, debit=principal),
            leg("2100", cid, debit=cost),
            leg("5000", cid, debit=e["broker_cost"]),
            leg("5010", cid, debit=e["custody_cost"]),
            leg("5100", cid, debit=e["partner"]),
            leg("2010", cid, credit=net),
            leg("1200", cid, credit=cost),
            leg("4000", cid, credit=e["brokerage"]),
            leg("4010", cid, credit=e["custody"]),
            leg("2400", cid, credit=e["reg"]),
            leg(e["payable"], cid, credit=e["broker_cost"]),
            leg("2420", cid, credit=e["custody_cost"]),
            leg("2430", cid, credit=e["partner"]),
        ]

    def on_trade_settled(self, p, ev):
        tid = p.get("trade_id")
        t = self.trades.get(tid)
        if t is None or t.status != "open":
            raise Rejected("unknown or already settled trade")
        t.status = "closed"
        cid, principal = t.customer_id, t.principal
        if t.side == "buy":
            return [leg("2350", cid, debit=principal), leg("1100", cid, credit=principal)]
        return [leg("1100", cid, debit=principal), leg("1150", cid, credit=principal)]

    def on_order_cancelled(self, p, ev):
        order = self.orders.get(p["order_id"])
        if order:
            order.cash_hold = ZERO
            order.status = "closed"
        return []

    def on_order_rejected(self, p, ev):
        return self.on_order_cancelled(p, ev)

    # -------------------------------------------------------------------
    # Settlement
    # -------------------------------------------------------------------

    def _settle_payable(self, cid, account):
        amount = self.payable_balance(cid, account)
        if amount <= ZERO:
            raise Rejected("nothing outstanding")
        return [leg(account, cid, debit=amount), leg("1100", cid, credit=amount)]

    def on_broker_fees_settled(self, p, ev):
        broker = p.get("broker")
        if broker not in BROKERS:
            raise Rejected("unknown broker")
        return self._settle_payable(p["customer_id"], BROKERS[broker]["payable"])

    def on_custodian_fees_settled(self, p, ev):
        return self._settle_payable(p["customer_id"], "2420")

    def on_reg_fees_remitted(self, p, ev):
        return self._settle_payable(p["customer_id"], "2400")

    def on_partner_payout(self, p, ev):
        return self._settle_payable(p["customer_id"], "2430")

    # -------------------------------------------------------------------
    # Corporate Actions
    # -------------------------------------------------------------------

    def on_dividend_cash(self, p, ev):
        net = amount_of(p, "net_amount")
        cid = p["customer_id"]
        return [leg("1100", cid, debit=net), leg("2010", cid, credit=net)]

    def on_dividend_reinvested(self, p, ev):
        net = amount_of(p, "net_amount")
        cid = p["customer_id"]
        rq = qty_of(p, "reinvest_quantity")
        self.lots[(cid, p["symbol"])].append(Lot(quantity=rq, total_cost=net))
        return [leg("1200", cid, debit=net), leg("2100", cid, credit=net)]

    def on_stock_split(self, p, ev):
        cid = p["customer_id"]
        ratio = D(str(p["ratio_to"])) / D(str(p["ratio_from"]))
        for lot in self.lots.get((cid, p["symbol"]), []):
            lot.quantity = shares(lot.quantity * ratio)
        return []

    def on_symbol_change(self, p, ev):
        cid = p["customer_id"]
        old, new = p["old_symbol"], p["new_symbol"]
        if (cid, old) in self.lots:
            moving = self.lots.pop((cid, old))
            self.lots[(cid, new)].extend(moving)
        return []

    # -------------------------------------------------------------------
    # Reversals
    # -------------------------------------------------------------------

    def on_reversal(self, p, ev):
        target = p["reverses_event_id"]
        if target not in self.posted or target in self.reversed_events:
            raise Rejected("unknown or already reversed event")
        self.reversed_events.add(target)

        original = self.legs_by_event[target]
        inverse = [leg(l["account"], l["customer_id"],
                       debit=D(l["credit"]), credit=D(l["debit"]))
                   for l in original]

        # Rebuild lots if this was a lot-affecting event
        for j_ev in reversed(self.journal):
            if j_ev["event_id"] == target:
                if j_ev["type"] in LOT_EVENTS:
                    self._rebuild_lots()
                break

        return inverse

    def _rebuild_lots(self):
        self.lots = defaultdict(deque)
        for ev in self.journal:
            eid = ev["event_id"]
            if eid not in self.posted or eid in self.reversed_events:
                continue
            if ev["type"] not in LOT_EVENTS:
                continue
            p = ev["payload"]
            try:
                if ev["type"] == "stock_split":
                    self.on_stock_split(p, ev)
                elif ev["type"] == "symbol_change":
                    self.on_symbol_change(p, ev)
                elif ev["type"] == "dividend_reinvested":
                    self.lots[(p["customer_id"], p["symbol"])].append(
                        Lot(qty_of(p, "reinvest_quantity"), amount_of(p, "net_amount"))
                    )
                elif p["side"] == "buy":
                    self.lots[(p["customer_id"], p["symbol"])].append(
                        Lot(qty_of(p, "quantity"), amount_of(p, "principal"))
                    )
                else:
                    self._relieve(p["customer_id"], p["symbol"], qty_of(p, "quantity"))
            except Rejected:
                continue

    def _relieve(self, cid, symbol, quantity):
        lots = self.lots[(cid, symbol)]
        available = sum((l.quantity for l in lots), ZERO)
        if quantity > available:
            raise Rejected("oversell")

        remaining = quantity
        cost = ZERO
        while remaining > 0 and lots:
            lot = lots[0]
            if lot.quantity <= remaining:
                cost += lot.total_cost
                remaining -= lot.quantity
                lots.popleft()
            else:
                part = money(lot.total_cost * remaining / lot.quantity)
                cost += part
                lot.total_cost -= part
                lot.quantity = shares(lot.quantity - remaining)
                remaining = ZERO
        return cost

    # -------------------------------------------------------------------
    # Snapshot
    # -------------------------------------------------------------------

    def snapshot(self, as_of_event_id=None) -> dict:
        if as_of_event_id is not None:
            return self._snapshot_as_of(as_of_event_id)

        tb: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for (_cid, acct), bal in self.balances.items():
            tb[acct] += bal

        customers: dict[str, dict] = {}
        for (cid, acct), bal in self.balances.items():
            c = customers.setdefault(cid, {"wallet_cash": ZERO, "cash_hold": ZERO, "positions": {}})
            if acct == "2010":
                c["wallet_cash"] += -bal

        for order in self.orders.values():
            if order.cash_hold > ZERO:
                c = customers.setdefault(
                    order.customer_id, {"wallet_cash": ZERO, "cash_hold": ZERO, "positions": {}})
                c["cash_hold"] += order.cash_hold

        for (cid, symbol), lot_list in self.lots.items():
            total_qty = sum(l.quantity for l in lot_list)
            total_cost = sum(l.total_cost for l in lot_list)
            if total_qty > ZERO:
                c = customers.setdefault(cid, {"wallet_cash": ZERO, "cash_hold": ZERO, "positions": {}})
                c["positions"][symbol] = {
                    "quantity": share_str(total_qty),
                    "cost_basis": money_str(total_cost),
                }

        open_routes = {}
        for oid, o in sorted(self.orders.items()):
            if o.status == "open":
                open_routes[oid] = o.route

        return {
            "trial_balance": {a: money_str(v) for a, v in sorted(tb.items())},
            "customers": {
                cid: {
                    "wallet_cash": money_str(c["wallet_cash"]),
                    "cash_hold": money_str(c["cash_hold"]),
                    "positions": c["positions"],
                }
                for cid, c in sorted(customers.items())
            },
            "open_order_routes": open_routes,
        }

    def _snapshot_as_of(self, event_id):
        replay = Book()
        for ev in self.journal:
            replay.apply(ev)
            if ev.get("event_id") == event_id:
                break
        return replay.snapshot()
