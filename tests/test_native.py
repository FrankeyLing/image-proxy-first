from pathlib import Path
import hashlib
import json
import os
import statistics
import struct
import subprocess
import tempfile
import time
import unittest
from PIL import Image, ImageDraw

SKILL=Path(__file__).resolve().parents[1]/'image-proxy-first'
import platform
ARCH='arm64' if platform.machine().lower() in ('arm64','aarch64') else 'x64'
SYSTEM='windows' if os.name=='nt' else 'linux'
EXE=SKILL/'bin'/(SYSTEM+'-'+ARCH)/('image-proxy.exe' if os.name=='nt' else 'image-proxy')
if os.name!='nt': EXE.chmod(EXE.stat().st_mode | 0o111)

class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='image-proxy-native-test-');cls.root=Path(cls.temp.name)
        cls.source=cls.root/'原图 中文 noisy.png'
        cls.image=Image.frombytes('RGB',(4000,3000),os.urandom(4000*3000*3))
        cls.image.save(cls.source)
        cls.before=hashlib.sha256(cls.source.read_bytes()).hexdigest()
        cls.n=0
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def call(self,*args,ok=True):
        type(self).n+=1;out=self.root/f'output-{self.n}'
        run=subprocess.run([str(EXE),*map(str,args),'--out-dir',str(out)],capture_output=True,text=True,encoding='utf-8')
        if not ok:
            self.assertNotEqual(run.returncode,0);return run
        self.assertEqual(run.returncode,0,run.stderr); data=json.loads(run.stdout)
        self.assertNotIn('data:image',run.stdout);self.assertLess(len(run.stdout),18000)
        for item in data['items']:
            self.assertEqual(json.loads((Path(item['output_directory'])/'manifest.json').read_text()),item)
            for proxy in item['proxies']:
                self.assertLessEqual(proxy['bytes'],item['max_bytes_each']);self.assertEqual(Path(proxy['path']).stat().st_size,proxy['bytes'])
                with Image.open(proxy['path']) as image:
                    self.assertEqual(list(image.size),proxy['dimensions']);self.assertFalse(image.getexif())
        return data
    def test_all_layouts_single_decode_geometry(self):
        data=self.call(self.source,'--layout','all')
        self.assertGreaterEqual(len(data['items'][0]['proxies']),9)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.before)
    def test_caps_and_crop(self):
        data=self.call(self.source,'--max-bytes','16000','--layout','overview')
        self.assertLessEqual(data['items'][0]['proxies'][0]['bytes'],16000)
        data=self.call(self.source,'--crop',100,200,500,400)
        self.assertEqual(data['items'][0]['proxies'][0]['dimensions'],[500,400])
        self.call(self.source,'--crop',0,0,999999,100,ok=False)
    def test_orientation_all_eight(self):
        image=Image.new('RGB',(80,40));draw=ImageDraw.Draw(image)
        draw.rectangle((0,0,39,19),fill='red');draw.rectangle((40,0,79,19),fill='green')
        draw.rectangle((0,20,39,39),fill='blue');draw.rectangle((40,20,79,39),fill='yellow')
        from PIL import ImageOps
        for orientation in range(1,9):
            source=self.root/f'orientation-{orientation}.jpg';exif=Image.Exif();exif[274]=orientation;image.save(source,exif=exif,quality=98)
            data=self.call(source,'--preset','fast')
            with Image.open(source) as original: expected=ImageOps.exif_transpose(original).convert('RGB')
            with Image.open(data['items'][0]['proxies'][0]['path']) as actual:
                self.assertEqual(actual.size,expected.size)
                for x,y in [(8,8),(actual.width-9,8),(8,actual.height-9)]:
                    self.assertLess(max(abs(a-b) for a,b in zip(actual.getpixel((x,y)),expected.getpixel((x,y)))),25)
    def test_raw_layouts(self):
        for endian,mode in [('<','raw-gray16le'),('>','raw-gray16be')]:
            source=self.root/(mode+'.raw');source.write_bytes(struct.pack(endian+'64H',*range(64))*32)
            data=self.call(source,'--mode',mode,'--width',64,'--height',32,'--layout','overview')
            command=data['items'][0]['ready_recipes'][0]['command_argv']
            run=subprocess.run(command+['--out-dir',str(self.root/(mode+'-recipe'))],capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            with Image.open(data['items'][0]['proxies'][0]['path']) as proxy:
                self.assertLess(proxy.getpixel((0,10))[0],10);self.assertGreater(proxy.getpixel((63,10))[0],245)
        self.call(source,ok=False)
        self.call(source,'--mode','raw-gray16le','--width',9999,'--height',9999,ok=False)
    def test_alpha_white(self):
        source=self.root/'alpha.png';Image.new('RGBA',(128,64),(255,0,0,0)).save(source)
        data=self.call(source,'--preset','fast')
        with Image.open(data['items'][0]['proxies'][0]['path']) as proxy:self.assertGreater(min(proxy.getpixel((20,20))),245)
    def test_batch(self):
        data=self.call(self.source,self.source,'--preset','fast');self.assertEqual(len(data['items']),2)
    def test_limits_and_corruption(self):
        self.call(self.source,'--max-input-pixels',1,ok=False)
        self.call(self.source,'--max-input-bytes',1,ok=False)
        self.call(self.source,'--max-bytes',999999,ok=False)
        path=self.root/'broken.jpg';path.write_bytes(b'not an image');self.call(path,ok=False)
    def test_existing_directory_rejected(self):
        out=self.root/'existing';out.mkdir();marker=out/'keep';marker.write_text('keep')
        run=subprocess.run([str(EXE),str(self.source),'--out-dir',str(out)],capture_output=True)
        self.assertNotEqual(run.returncode,0);self.assertEqual(marker.read_text(),'keep')
    @unittest.skipUnless(os.name=='nt','Windows launcher regression; native core is tested on both systems.')
    def test_python_fallback_automatic(self):
        path=self.root/'不支持的容器 Chinese.tiff';self.image.resize((2000,1500)).save(path)
        run=subprocess.run(['cmd.exe','/c',str(SKILL/'scripts/proxy.cmd'),str(path),'--out-dir',str(self.root/'fallback')],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(json.loads(run.stdout)['engine'],'python-fallback')

if __name__=='__main__':unittest.main()
