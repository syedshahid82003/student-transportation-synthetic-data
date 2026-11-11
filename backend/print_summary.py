"""Print assignment summary stats for starter and full scales."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
from collections import Counter

from backend.app.core.config import SEED
from backend.app.generators.master_data import generate_master_data
from backend.app.generators.route_generator import generate_routes
from backend.app.services.assignment_service import assign_all_students
from backend.app.services.capacity_service import (
    build_capacity_history,
    compute_utilisation,
    _EFF_START,
)

for scale in ["starter", "full"]:
    print(f"\n{'='*60}")
    print(f"  SCALE: {scale.upper()}")
    print(f"{'='*60}")

    master = generate_master_data(scale)
    rng    = np.random.default_rng(SEED)
    routes, route_stops = generate_routes(
        master["buses"], master["drivers"],
        master["stops"], master["students"], rng,
    )
    result  = assign_all_students(master, routes, route_stops, np.random.default_rng(SEED))
    history = build_capacity_history(master["buses"])
    util    = compute_utilisation(routes, result["assignments"], history, _EFF_START)

    asn = result["assignments"]
    rej = result["rejections"]

    n_students = len(master["students"])
    print(f"  Students total     : {n_students:>6}")
    print(f"  Assigned           : {len(asn):>6}")
    print(f"  Rejected           : {len(rej):>6}")

    if not rej.empty:
        code_counts: Counter = Counter()
        for codes in rej["error_codes"]:
            for c in codes:
                code_counts[c] += 1
        print("  Rejections by code:")
        for code, cnt in sorted(code_counts.items()):
            print(f"    {code:<40} {cnt:>5}")

    total_routes    = len(routes)
    feasible_routes = int(routes["is_feasible"].sum())
    active_routes   = routes[routes["status"] == "active"]
    print(f"  Feasible routes    : {feasible_routes:>4} / {total_routes}")
    print(f"  Active routes      : {len(active_routes):>4}")

    total_cap    = int(util["capacity"].sum())
    total_assign = int(util["assigned_students"].sum())
    overall_util = round(total_assign / total_cap * 100, 1) if total_cap else 0.0
    print(f"  Overall bus util   : {total_assign} / {total_cap} seats = {overall_util}%")
