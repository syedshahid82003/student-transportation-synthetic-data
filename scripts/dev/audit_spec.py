import sys, os, pathlib
os.environ['DATA_SCALE'] = 'starter'
sys.path.insert(0, r'C:\CandidateWorkspace')

print('=== SPEC COVERAGE ===')

dd = pathlib.Path(r'C:\CandidateWorkspace\docs\data_dictionary.md')
content = dd.read_text(encoding='utf-8')
entities = ['students','guardian_contacts','address_zones','stops','buses',
            'drivers','routes','route_stops','assignments','attendance_events',
            'notifications','audit_events','bus_capacity_history']
print('--- data_dictionary.md ---')
for e in entities:
    print('  ' + e + ': ' + ('FOUND' if e in content else 'MISSING'))

erd = pathlib.Path(r'C:\CandidateWorkspace\docs\erd.md')
et = erd.read_text(encoding='utf-8')
print('--- erd.md lines:', len(et.splitlines()),
      'mermaid:', ('erDiagram' in et or 'mermaid' in et.lower()))

ids_py = pathlib.Path(r'C:\CandidateWorkspace\backend\app\core\ids.py').read_text()
print('--- ids.py patterns ---')
for p in ['STU-','STOP-','BUS-','ROUTE-','ASN-','NOT-','DRV-','GRD-','ZONE-']:
    print('  ' + p + ': ' + ('present' if p in ids_py else 'MISSING'))

setup = pathlib.Path(r'C:\CandidateWorkspace\docs\setup.md')
st = setup.read_text(encoding='utf-8')
print('--- setup.md lines:', len(st.splitlines()),
      'seed:', ('20261022' in st), 'run cmds:', ('python' in st.lower()))

gt = pathlib.Path(r'C:\CandidateWorkspace\data\ground_truth')
print('--- data/ground_truth exists:', gt.exists(),
      'files:', [f.name for f in gt.iterdir()])

gi = pathlib.Path(r'C:\CandidateWorkspace\.gitignore')
print('--- .gitignore root:', gi.exists())

exp = pathlib.Path(r'C:\CandidateWorkspace\scripts\export_frontend_data.py')
print('--- export script:', exp.exists(), 'bytes:', exp.stat().st_size)

rep = list(pathlib.Path(r'C:\CandidateWorkspace').rglob('reprod*.py'))
print('--- reproducibility scripts:', [str(x) for x in rep])

csvs = [x for x in pathlib.Path(r'C:\CandidateWorkspace\data').rglob('*.csv')]
sqls = [x for x in pathlib.Path(r'C:\CandidateWorkspace\data').rglob('*.sql')]
print('--- CSV in data/:', len(csvs), '  SQL in data/:', len(sqls))

mans = list(pathlib.Path(r'C:\CandidateWorkspace').rglob('manifest*'))
mans = [str(x) for x in mans if 'node_modules' not in str(x) and '__pycache__' not in str(x)]
print('--- manifest files:', mans)

chks = list(pathlib.Path(r'C:\CandidateWorkspace').rglob('*checksum*')) + \
       list(pathlib.Path(r'C:\CandidateWorkspace').rglob('*sha256*'))
chks = [str(x) for x in chks if 'node_modules' not in str(x)]
print('--- checksum files:', chks)

api_routes = list(pathlib.Path(r'C:\CandidateWorkspace\backend\app\api\routes').glob('*.py'))
print('--- API route files:', [x.name for x in api_routes])

val = pathlib.Path(r'C:\CandidateWorkspace\backend\app\validators\__init__.py')
print('--- backend validators dir populated:', val.read_text().strip() != '')

print()
print('=== validate_dataset.py function list ===')
vd = pathlib.Path(r'C:\CandidateWorkspace\backend\app\validation\validate_dataset.py')
for ln in vd.read_text().splitlines():
    if ln.startswith('def '):
        print(' ', ln.strip())
