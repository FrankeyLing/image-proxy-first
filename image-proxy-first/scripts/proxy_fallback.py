"""Rare codec fallback with the same one-command proxy/regions interface."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import warnings
import image_proxy as codec
from PIL import Image

def regions(w, h, args):
    if args.crop:
        x, y, width, height = args.crop
        codec.require(x >= 0 and y >= 0 and width > 0 and height > 0 and x+width <= w and y+height <= h, 'Crop outside oriented source.')
        return [('crop', (x,y,width,height))]
    result = [('overview', (0,0,w,h))]
    layout = args.layout
    if layout == 'smart':
        layout = 'overview' if args.preset == 'fast' else 'grid' if args.preset == 'detail' else 'halves' if args.preset == 'text' or max(w,h)>args.max_edge else 'overview'
    if layout in ('halves','all'):
        if h >= w:
            center=(h+1)//2; overlap=max(1,h//20); start=max(0,center-overlap)
            result += [('top',(0,0,w,min(h,center+overlap))),('bottom',(0,start,w,h-start))]
        else:
            center=(w+1)//2; overlap=max(1,w//20); start=max(0,center-overlap)
            result += [('left',(0,0,min(w,center+overlap),h)),('right',(start,0,w-start,h))]
    if layout in ('grid','all'):
        for y in range(2):
            for x in range(2):
                x0=x*w//2; y0=y*h//2; x1=(x+1)*w//2; y1=(y+1)*h//2
                if x1>x0 and y1>y0: result.append((f'grid-{y}{x}',(x0,y0,x1-x0,y1-y0)))
    if layout in ('strips','all'):
        vertical=h>=w; length=h if vertical else w; count=min(4,max(2,(length+(w if vertical else h)-1)//(w if vertical else h)))
        for k in range(count):
            start=k*length//count; end=(k+1)*length//count
            result.append((f'strip-{k}',(0,start,w,end-start) if vertical else (start,0,end-start,h)))
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='+',type=Path)
    parser.add_argument('--out-dir',type=Path)
    parser.add_argument('--preset',choices=['fast','balanced','text','detail'],default='balanced')
    parser.add_argument('--layout',choices=['smart','overview','halves','grid','strips','all'],default='smart')
    parser.add_argument('--mode',default='auto')
    parser.add_argument('--max-bytes',type=int)
    parser.add_argument('--max-edge',type=int)
    parser.add_argument('--max-input-pixels',type=int,default=160000000)
    parser.add_argument('--max-input-bytes',type=int,default=1073741824)
    parser.add_argument('--crop',nargs=4,type=int)
    for name in ['width','height','stride']:
        parser.add_argument('--'+name,type=int)
    parser.add_argument('--offset',type=int,default=0)
    parser.add_argument('--frame',type=int,default=0)
    parser.add_argument('--time',type=float)
    parser.add_argument('--black',type=float)
    parser.add_argument('--white',type=float)
    parser.add_argument('--allow-trailing',action='store_true')
    args=parser.parse_args()
    args.max_bytes=args.max_bytes or (96000 if args.preset=='fast' else 300000 if args.preset=='detail' else 240000)
    args.max_edge=args.max_edge or (1280 if args.preset=='fast' else 2048 if args.preset=='detail' else 1600)
    args.max_decode_bytes=args.max_input_bytes
    codec.require(16000<=args.max_bytes<=500000 and 64<=args.max_edge<=2048,'Invalid proxy limits.')
    codec.require(1<=len(args.source)<=16 and args.max_input_pixels>0 and args.max_input_bytes>0 and args.frame>=0,'Invalid input limits.')
    args.out_dir=(args.out_dir or Path(tempfile.gettempdir())/f'codex-image-proxy-python-{time.time_ns()}').absolute()
    codec.require(not args.out_dir.exists(),'Output directory exists.')
    if len(args.source)>1: args.out_dir.mkdir(parents=True,exist_ok=False)
    items=[]
    for index,path in enumerate(args.source):
        started=time.perf_counter(); path=path.expanduser().resolve(strict=True)
        before=codec.identity(path); codec.require(0<before[2]<=args.max_input_bytes,'Source byte limit.')
        mode=args.mode
        if mode=='auto':
            codec.require(path.suffix.lower() not in {'.raw','.bin'},'Raw geometry needs explicit mode and dimensions.')
            mode='camera-raw' if path.suffix.lower() in codec.CAMERA else 'video' if path.suffix.lower() in codec.VIDEOS else 'image'
        current=SimpleNamespace(**vars(args)); current.mode=mode; notes=[]
        Image.MAX_IMAGE_PIXELS=args.max_input_pixels;warnings.simplefilter('error',Image.DecompressionBombWarning)
        if mode in codec.RAW_MODES: image=codec.raw_input(path,current,notes)
        elif mode=='video':
            codec.require(args.crop is None,'Video crop requires an unscaled separately extracted frame.')
            image=codec.video_input(path,current,notes)
        elif mode=='camera-raw':image=codec.camera_input(path,current,notes)
        else:
            codec.require(mode=='image','Unsupported mode.')
            image=codec.image_input(path,current,notes)
        codec.require(image.width*image.height<=args.max_input_pixels,'Input pixel limit.')
        image=codec.grayscale(image,args.black,args.white,notes)
        if 'A' in image.getbands() or 'transparency' in image.info:
            rgba=image.convert('RGBA'); white=Image.new('RGBA',rgba.size,'white');white.alpha_composite(rgba);image=white.convert('RGB')
        else: image=image.convert('RGB')
        decoded=time.perf_counter(); folder=args.out_dir if len(args.source)==1 else args.out_dir/str(index+1)
        folder.mkdir(parents=True,exist_ok=False); proxies=[]
        for name,box in regions(image.width,image.height,args):
            x,y,w,h=box; data,size,quality=codec.encode_proxy(image.crop((x,y,x+w,y+h)),args.max_edge,args.max_bytes)
            target=folder/(name+'.jpg')
            with target.open('xb') as stream:
                codec.require(stream.write(data)==len(data),'Short write.');stream.flush();os.fsync(stream.fileno())
            codec.require(target.stat().st_size==len(data)<=args.max_bytes,'Proxy byte cap.')
            proxies.append({'name':name,'path':str(target),'crop':list(box),'dimensions':list(size),'bytes':len(data),'encoded_base64_bytes':4*((len(data)+2)//3),'quality':quality})
        codec.require(codec.identity(path)==before,'Source changed.')
        decoding=['--mode',mode,'--max-input-pixels',str(args.max_input_pixels),'--max-input-bytes',str(args.max_input_bytes)]
        for key in ['width','height','stride','offset','frame','time','black','white']:
            if getattr(args,key) is not None:decoding+=['--'+key,str(getattr(args,key))]
        if args.allow_trailing:decoding+=['--allow-trailing']
        if args.crop:decoding+=['--crop',*map(str,args.crop)]
        item={'engine':'python-fallback','source':str(path),'source_bytes':before[2],'oriented_dimensions':list(image.size),
              'max_bytes_each':args.max_bytes,'output_directory':str(folder),'decode_ms':(decoded-started)*1000,
              'total_ms':(time.perf_counter()-started)*1000,'total_proxy_bytes':sum(x['bytes'] for x in proxies),'proxies':proxies,'notes':notes,
              'ready_recipes':[{'label':x,'command_argv':[sys.executable,str(Path(__file__).resolve()),str(path),'--layout',x,*decoding]} for x in ['overview','halves','grid','strips']]}
        with (folder/'manifest.json').open('x',encoding='utf-8') as stream:json.dump(item,stream,ensure_ascii=False)
        items.append(item)
    print(json.dumps({'engine':'python-fallback','items':items},ensure_ascii=False))

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr,'reconfigure'):sys.stderr.reconfigure(encoding='utf-8')
    try:main()
    except Exception as error:
        print(json.dumps({'ready':False,'error':str(error)},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
