import pytest
from decimal import Decimal
from book import Book
from models import ZERO, Rejected
from utils import amount_of, qty_of

def test_deposit():
    book = Book()
    ev = {
        "event_id": "e1",
        "type": "deposit",
        "payload": {"customer_id": "C1", "amount": "100.00"}
    }
    legs = book.apply(ev)
    assert len(legs) == 2
    assert book.balances[("C1", "1100")] == Decimal("100.00")
    assert book.balances[("C1", "2010")] == Decimal("-100.00")

def test_order_placed_and_filled():
    book = Book()
    ev_place = {
        "event_id": "e2",
        "type": "order_placed",
        "payload": {
            "customer_id": "C1", "order_id": "o1", "side": "buy",
            "symbol": "AAPL", "quantity": "10.00", "limit_price": "150.00",
            "est_charges": "5.00"
        }
    }
    book.apply(ev_place)
    assert "o1" in book.orders
    assert book.orders["o1"].initial_hold == Decimal("1505.00")

    ev_fill = {
        "event_id": "e3",
        "type": "order_filled",
        "payload": {
            "customer_id": "C1", "order_id": "o1", "side": "buy",
            "symbol": "AAPL", "quantity": "10.00", "principal": "1500.00",
            "broker": "BRK-A", "trade_id": "t1"
        }
    }
    legs = book.apply(ev_fill)
    assert len(legs) > 0
    assert book.orders["o1"].cash_hold == ZERO
    assert book.orders["o1"].status == "closed"

def test_amount_of_rejected():
    with pytest.raises(Rejected):
        amount_of({"amount": "invalid"}, "amount")
