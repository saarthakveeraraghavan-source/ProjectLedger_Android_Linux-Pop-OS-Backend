"""Resume Google's AOSP test image with eight bounded range transfers; verify official SHA-1."""
import concurrent.futures
import hashlib
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
tools=root/'.tools'
url='https://dl.google.com/android/repository/sys-img/android/x86_64-35_r02.zip'
index=tools/'system-images.xml'
subprocess.run(['curl','-fsSL','--max-time','60','-o',str(index),'https://dl.google.com/android/repository/sys-img/android/sys-img2-3.xml'],check=True)
xml=ET.parse(index)
expected=None
for package in xml.getroot().iter():
    if package.attrib.get('path')=='system-images;android-35;default;x86_64':
        for archive in package.iter():
            if archive.tag.split('}')[-1]=='complete':
                fields={child.tag.split('}')[-1]:child.text for child in archive}
                if fields.get('url')=='x86_64-35_r02.zip': expected=fields
assert expected is not None
source=tools/'system-image.zip'
total=int(expected['size']); size=source.stat().st_size
if size < total:
    step=(total-size+7)//8
    ranges=[(start,min(start+step-1,total-1)) for start in range(size,total,step)]
    def download(item):
        number,(start,end)=item
        target=tools/f'image-range-{number}.part'
        if not target.exists() or target.stat().st_size!=end-start+1:
            subprocess.run(['curl','-fsSL','--retry','3','--max-time','600','--range',f'{start}-{end}','-o',str(target),url],check=True)
        if target.stat().st_size!=end-start+1: raise RuntimeError('Range size mismatch')
        print('Completed range',number,flush=True)
        return target
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        parts=list(executor.map(download,enumerate(ranges)))
    with source.open('ab') as out:
        for part in parts:
            with part.open('rb') as inp:
                while chunk:=inp.read(1024*1024): out.write(chunk)
assert source.stat().st_size==total
with source.open('rb') as handle: assert hashlib.file_digest(handle,'sha1').hexdigest()==expected['checksum']
with zipfile.ZipFile(source) as archive:
    assert archive.testzip() is None
    destination=tools/'sdk/system-images/android-35/default'
    archive.extractall(destination)
print('Official checksum and ZIP verified; image extracted.',flush=True)
