import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
from backend.app.core.config import SEED
from backend.app.generators.master_data import generate_master_data
from backend.app.generators.route_generator import _allocate_zones_to_buses

master = generate_master_data('starter')
rng = np.random.default_rng(SEED)
allocs = _allocate_zones_to_buses(master['students'], master['stops'], master['buses'], rng)
acc = [a for a in allocs if a['is_accessible']]
for a in acc:
    print(a['bus_id'], len(a['zone_ids']), 'zones:', a['zone_ids'])
print('Total acc zones covered:', len(set(z for a in acc for z in a['zone_ids'])))
