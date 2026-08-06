import pytest
from decimal import Decimal
from book import Book
from models import ZERO, Rejected
from utils import amount_of, qty_of, money, shares

def test_deposit():
    """Test valid deposit posting logic."""
    book = Book()
    ev = {
        "event_id": "evt_deposit_001",
        "type": "deposit",
        "payload": {"customer_id": "CUST-A", "amount": "100.00"}
    }
    legs = book.apply(ev)
    assert len(legs) == 2
    assert book.balances[("CUST-A", "1100")] == Decimal("100.00")
    assert book.balances[("CUST-A", "2010")] == Decimal("-100.00")

def test_invalid_deposit_amount_rejected():
    """Test that malformed string amounts are safely rejected."""
    book = Book()
    ev = {
        "event_id": "evt_deposit_invalid",
        "type": "deposit",
        "payload": {"customer_id": "CUST-A", "amount": "not-a-number"}
    }
    legs = book.apply(ev)
    assert legs == []
    # Assert nothing touched
    assert ("CUST-A", "1100") not in book.balances

def test_order_placed_and_filled():
    """Test full order lifecycle: placement creates hold, fill releases hold and posts legs."""
    book = Book()
    ev_place = {
        "event_id": "evt_platest_order_placed_and_filledce_001",
        "type": "order_placed",
        "payload": {
            "customer_id": "CUST-A", "order_id": "ORD-1", "side": "buy",
            "symbol": "AAPL", "quantity": "10.00", "limit_price": "150.00",
            "est_charges": "5.00"
        }
    }
    book.apply(ev_place)
    
    # Verify order state and initial cash hold (qty * price + est_charges)
    assert "ORD-1" in book.orders
    assert book.orders["ORD-1"].initial_hold == Decimal("1505.00")
    assert book.orders["ORD-1"].cash_hold == Decimal("1505.00")
    assert book.orders["ORD-1"].status == "open"

    ev_fill = {
        "event_id": "evt_fill_001",
        "type": "order_filled",
        "payload": {
            "customer_id": "CUST-A", "order_id": "ORD-1", "side": "buy",
            "symbol": "AAPL", "quantity": "10.00", "principal": "1500.00",
            "broker": "BRK-A", "trade_id": "TRD-1"
        }
    }
    legs = book.apply(ev_fill)
    
    assert len(legs) > 0
    # Hold must be completely wiped on final fill
    assert book.orders["ORD-1"].cash_hold == ZERO
    assert book.orders["ORD-1"].status == "closed"
    
    # Ensure FIFO lot is created
    assert len(book.lots[("CUST-A", "AAPL")]) == 1
    assert book.lots[("CUST-A", "AAPL")][0].quantity == Decimal("10.00")

def test_reversal_logic():
    """Test that a reversed event successfully reconstructs the exact opposite legs and clears the lot."""
    book = Book()
    ev_buy = {
        "event_id": "evt_fill_002",
        "type": "order_filled",
        "payload": {
            "customer_id": "CUST-A", "order_id": "ORD-2", "side": "buy",
            "symbol": "AAPL", "quantity": "10.00", "principal": "1500.00",
            "broker": "BRK-A", "trade_id": "TRD-2"
        }
    }
    book.apply(ev_buy)
    assert len(book.lots[("CUST-A", "AAPL")]) == 1

    ev_reverse = {
        "event_id": "evt_reverse_001",
        "type": "reversal",
        "payload": {
            "reverses_event_id": "evt_fill_002"
        }
    }
    legs = book.apply(ev_reverse)
    assert len(legs) > 0 # Assert inverse legs were generated
    # The lot should be cleared because it rebuilt state minus the reversed event
    assert len(book.lots[("CUST-A", "AAPL")]) == 0

def test_amount_of_rejected_helper():
    """Test utils validation logic."""
    with pytest.raises(Rejected):
        amount_of({"amount": "invalid"}, "amount")
