"""Optional convenience entry. Native installation itself does not need Python."""
import argparse
import os
from pathlib import Path
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('--replace-existing',action='store_true')
parser.add_argument('--with-python-fallback',action='store_true')
parser.add_argument('--extras',action='store_true')
args=parser.parse_args()
root=Path(__file__).resolve().parent
if os.name=='nt':
    command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'install.ps1')]
    for key,value in vars(args).items():
        if value: command.append('-'+''.join(word.capitalize() for word in key.split('_')))
else:
    command=['sh',str(root/'install.sh')]
    for key,value in vars(args).items():
        if value: command.append('--'+key.replace('_','-'))
raise SystemExit(subprocess.call(command))
