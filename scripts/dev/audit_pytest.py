import sys, os, pathlib, time
os.environ['DATA_SCALE'] = 'starter'
sys.path.insert(0, r'C:\CandidateWorkspace')
import numpy as np
import subprocess, hashlib, pickle
from backend.app.core.config import SEED, SCALES

print('=== PYTEST STARTER ===')
t0 = time.time()
r = subprocess.run(
    ['python', '-m', 'pytest', 'tests/', '-q', '--tb=no', '--no-header'],
    cwd=r'C:\CandidateWorkspace\backend',
    capture_output=True, text=True, timeout=300,
    env={**os.environ, 'DATA_SCALE': 'starter'}
)
t1 = time.time()
out = r.stdout + r.stderr
for line in out.splitlines()[-8:]:
    print(line)
print('runtime:', round(t1-t0, 1), 's')
