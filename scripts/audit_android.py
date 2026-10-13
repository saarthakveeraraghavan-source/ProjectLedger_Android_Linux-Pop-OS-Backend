"""Query OSV with package coordinates only, never project financial data."""
import json
import re
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
text=(root/'docs/android-dependencies.txt').read_text()
coordinates=set()
for line in text.splitlines():
    match=re.search(r'([\w.-]+):([\w.-]+):([\w.-]+)(?: -> ([\w.-]+))?',line)
    if match:
        group,artifact,version,resolved=match.groups()
        coordinates.add((group+':'+artifact,resolved or version))
results=[]
with httpx.Client(timeout=60) as client:
    packages=sorted(coordinates)
    for offset in range(0,len(packages),100):
        batch=packages[offset:offset+100]
        response=client.post('https://api.osv.dev/v1/querybatch',json={'queries':[{'package':{'ecosystem':'Maven','name':name},'version':version} for name,version in batch]})
        response.raise_for_status()
        results.extend({'package':name,'version':version,'vulnerabilities':item.get('vulns',[])} for (name,version),item in zip(batch,response.json()['results'],strict=True))
report={'source':'https://api.osv.dev/v1/querybatch','scope':'resolved debug runtime Maven dependencies','packages':results,'findings':sum(len(p['vulnerabilities']) for p in results)}
(root/'docs/android-security-audit.json').write_text(json.dumps(report,indent=2))
print('Packages checked:',len(results),'findings:',report['findings'])
for item in results:
    if item['vulnerabilities']: print(item['package'],item['version'],item['vulnerabilities'])
