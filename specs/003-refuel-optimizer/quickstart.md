# Quickstart: Refuel Optimizer (003)

Everything here runs offline. No database, no network.

## 1. Tests

```bash
python -m pytest tests/unit/planner/test_optimizer.py tests/unit/planner/test_oracle_agreement.py \
  --cov=planner.optimizer --cov-report=term-missing
```

Expected: all green, the oracle agrees on every seeded case, coverage of `planner/optimizer.py`
≥ 95% (SC-001, SC-007).

## 2. A hand-checked plan

```bash
python -c "
from decimal import Decimal as D
from planner.optimizer import PlanStation, plan_refuelling
s = [PlanStation(1, D('300'), D('3.50')), PlanStation(2, D('450'), D('3.00'))]
p = plan_refuelling(D('900'), s, mpg=D(10), max_range_miles=D(500))
print(p)"
```

Expected: the full tank passes mile 300 without buying (the cheaper station at 450 is in range);
at 450 the truck has 5 gal and buys 40 gal at $3.00 to reach the finish
with 0 left: one purchase, 40 gal, $120.00.

## 3. Infeasible results

```bash
python -c "
from decimal import Decimal as D
from planner.optimizer import PlanStation, plan_refuelling, InfeasibleRoute
for start, stations, dist in [(None, [PlanStation(1, D(100), D(3)), PlanStation(2, D(700), D(3))], D(800)),
                              (D(10), [PlanStation(1, D(150), D(3))], D(300))]:
    try: plan_refuelling(dist, stations, mpg=D(10), max_range_miles=D(500), start_fuel_gallons=start)
    except InfeasibleRoute as e: print(e)"
```

Expected: `station gap` from mile 100 to 700; `start fuel insufficient`: 10 gal covers 100 mi, next
fuel point at mile 150, 5 gal short.

## 4. Timing (SC-006, by hand)

Time `plan_refuelling` on the 202 real Dallas → Chicago candidates (Feature 002 quickstart §3,
converted as in the contract) and on a synthetic 3,000-mile list of ~400 stations. Target: well
under 10 ms. Record the figures and the machine in the README.
