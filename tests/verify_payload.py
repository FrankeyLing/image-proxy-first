from pathlib import Path
import hashlib
import json
root=Path(__file__).resolve().parents[1]
payload=root/'image-proxy-first'
manifest=json.loads((root/'payload-sha256.json').read_text(encoding='utf-8'))
for name,expected in manifest.items():
    path=payload/name
    assert path.is_file(),name
    assert hashlib.sha256(path.read_bytes()).hexdigest()==expected,name
assert 'MIT License' in (root/'LICENSE').read_text(encoding='utf-8')
print('Payload digests verified:',len(manifest))
