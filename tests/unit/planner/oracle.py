"""Brute-force oracle for the refuelling optimizer (research R6).

A DP over (station, whole fuel units on arrival) on small integer instances with mpg = 1, so one
unit is one gallon and one mile. With integer distances an optimal plan buys whole units at every
stop, so this finds the same minimum cost as the continuous problem.
"""

import random

Station = tuple[int, int, int]  # (opis_id, mile, price)


def oracle_cost(
    distance: int, stations: list[Station], capacity: int, start_fuel: int
) -> int | None:
    """Minimum total cost to drive `distance`, or None when no plan exists."""
    miles = [mile for _, mile, _ in stations] + [distance]
    if miles[0] > start_fuel:
        return None  # fuel cannot be bought at the start

    # best[f] = cheapest cost of arriving at the current station with f units
    best = {start_fuel - miles[0]: 0}
    for k, (_, mile, price) in enumerate(stations):
        leg = miles[k + 1] - mile
        arrived = {}
        for fuel, cost in best.items():
            for bought in range(capacity - fuel + 1):
                left = fuel + bought - leg
                if left >= 0:
                    total = cost + bought * price
                    if total < arrived.get(left, total + 1):
                        arrived[left] = total
        if not arrived:
            return None
        best = arrived
    return min(best.values())


def random_instance(rng: random.Random) -> tuple[int, list[Station], int, int]:
    """A small random trip: (distance, stations sorted by (mile, opis_id), capacity, start fuel)."""
    capacity = rng.randint(5, 15)
    distance = rng.randint(0, 40)
    count = rng.randint(0, 8)
    stations = [
        (opis_id, rng.randint(0, distance), rng.randint(1, 9)) for opis_id in range(1, count + 1)
    ]
    stations.sort(key=lambda s: (s[1], s[0]))
    return distance, stations, capacity, rng.randint(0, capacity)
