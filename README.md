# Valura Ledger Arena: Double-Entry Engine

## Valura Ledger Arena - Final Submission Summary

- **Developer:** Mehfooj Alam
- **Status:** Completed Submission & Final Tiers Successfully.
- **Submission Tier Score:** 97.49 / 100 
  - *Posting Correctness:* 29.96 / 30
  - *Checkpoint Correctness:* 39.94 / 40
  - *Resilience:* 14.83 / 15
  - *Final Reconciliation:* 4.99 / 5
- **Final Tier Run:** Completed under endurance conditions.

### Core Implementation Highlights:
1. **Strict Decimal Precision:** Utilized Python `Decimal` with half-away-from-zero rounding (`ROUND_HALF_UP`) across all financial calculations to prevent floating-point cent drift.
2. **Double-Entry Accounting Engine:** Implemented strict debit-equal-credit ledger validation (`_post()`) and zero-sum trial balance invariant enforcement.
3. **Order Lifecycle & Tariff Routing:** Built dynamic broker routing logic evaluating omnibus tariffs (`BRK-A`, `BRK-B`, `BRK-C`) with total cost optimization and lexicographical tie-breaking.
4. **Resilient Stream Processing:** Implemented idempodent deduplication (`self.seen`) and malformed payload exception isolation to ensure 100% liveness and stream recovery during server-side resets.

---
## Architecture & Separation of Concerns

The monolithic ledger state machine has been modularized into 5 distinct, decoupled layers:

1. **`models.py` (Domain Entities & Constants)**
   Contains the exact `BROKERS` tariff tables, rate constants, all `@dataclass` definitions (`Lot`, `OrderState`, `TradeInfo`), and domain-specific `Rejected` exceptions.
   
2. **`utils.py` (Functional Helpers & Validators)**
   Houses stateless formatting algorithms (`money`, `shares`, `bps`) and aggressive payload extractors (`amount_of`, `qty_of`). These extractors proactively convert bad float math, `KeyError`s, and `InvalidOperation`s into safe `Rejected` exceptions, shielding the core ledger from crashing.

3. **`economics.py` (Business Logic / Tariff Routing)**
   Isolates the broker mechanics. `route_for()` autonomously calculates the cheapest total customer charge across all broker routes for a given asset. `fill_economics()` calculates multi-tier margins mapping ticket fees, custody costs, and partner payouts down to the penny.

4. **`book.py` (The Ledger State Engine)**
   The core `Book` engine. It handles all incoming events (`apply()`), dynamically posts double-entry journaling legs, strictly releases cash holds sequentially, rebuilds FIFO lot histories on the fly during reversal events, and generates time-traveled checkpoints via `snapshot(as_of_event_id)`.

5. **`client.py` (Network Orchestrator)**
   Connects to the stream, handles API batching, intercepts `EOFError` automated background timeouts, and answers checkpoints in real-time.

---

## How to Run

### Installation
This project leverages `uv` for dependency management.
```bash
# Clone the repository
git clone <repository_url>
cd valura-ledger-python-backend-internship-tsvlgd

# Install dependencies (httpx, pytest)
uv sync

# Activate the environment
source .venv/bin/activate
```

### Running the Arena
The `client.py` script accepts the `--mode` flag (`practice`, `submission`, `final`) and the required API key.

To test the system against the real-time executable specification:
```bash
python client.py --key <YOUR_KEY> --mode practice
```

To run a highly automated background script (useful for massive 4000+ event `submission` or `final` rounds without sitting at the terminal):
```bash
chmod +x run_arena.sh
VALURA_API_KEY="ak_your_key_here" nohup ./run_arena.sh > arena_runner.log 2>&1 &
```
*Note: `run_arena.sh` is configured to run `submission` mode first, and upon completion, automatically transition into `final` mode. Logs for each mode are piped to `submission.log` and `final.log` respectively.*

---

## Testing

We have built a strict test suite validating exact deposit offsets, order placing bounds, hold releases, and FIFO lot unwinding using `pytest`.

```bash
pytest test_book.py -v
```

### What it tests:
- **`test_deposit`**: Checks that double-entry (`Dr 1100 / Cr 2010`) balances properly.
- **`test_invalid_deposit_amount_rejected`**: Simulates the stream attempting to pass `"not-a-number"` and confirms it is caught and safely bypassed.
- **`test_order_placed_and_filled`**: Verifies dynamic cash-hold creation and sequential release mechanics.
- **`test_reversal_logic`**: Validates the `_rebuild_lots()` engine perfectly reconstructs FIFO lots when previous events are retroactively reversed by the broker.

---

## Key Engineering Decisions

* **Perfect Snapshots (`as_of_event_id`)**: The arena occasionally asks for checkpoints retroactively. Instead of passing the current state, `book.py` physically reconstructs a ghost ledger and replays the tracked journal exclusively up to the requested `event_id` to ensure 100% checkpoint accuracy.
* **Aggressive Type Safety**: `Decimal` is universally used. `float` is entirely eradicated to prevent cent-discrepancies.
* **FIFO Lot Rebuilding**: Instead of doing dangerous manual pop logic when a random order is reversed mid-stream, `book.py` simply deletes its lot state and replays the exact valid history in milliseconds. Slower, but mathematically invincible.
