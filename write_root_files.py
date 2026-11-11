import pathlib, textwrap
root = pathlib.Path(r'C:\CandidateWorkspace')
(root/'.gitignore').write_text('# Python\n__pycache__/\n*.py[cod]\n.env\n!.env.example\nvenv/\n.venv/\n.pytest_cache/\n.coverage\n# Node\nnode_modules/\nfrontend/dist/\n# OS\n.DS_Store\nThumbs.db\n# Generated output\ndata/generated/*.csv\ndata/generated/*.json\ndata/generated/*.sql\ndata/ground_truth/*.csv\ndata/ground_truth/*.json\n!data/generated/.gitkeep\n!data/ground_truth/.gitkeep\n', encoding='utf-8')
print('gitignore:', (root/'.gitignore').stat().st_size, 'bytes')

