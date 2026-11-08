"""Decode locally, cap a visual proxy, print only metadata, never base64."""
from __future__ import annotations
import argparse
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import warnings
try:
    from PIL import Image, ImageOps
except ImportError:
    raise SystemExit('Pillow missing. Run the package installer or use the skill private Python.')

RAW_MODES = {'raw-gray8': (1, 'L'), 'raw-gray16le': (2, 'I;16'),
             'raw-gray16be': (2, 'I;16B'), 'raw-rgb24': (3, 'RGB'),
             'raw-bgr24': (3, 'BGR'), 'raw-rgba32': (4, 'RGBA')}
CAMERA = {'.dng', '.cr2', '.cr3', '.nef', '.arw', '.orf', '.rw2', '.raf', '.pef'}
VIDEOS = {'.mp4', '.mov', '.mkv', '.avi', '.m4v', '.webm', '.mts', '.m2ts'}

def require(condition, message):
    if not condition:
        raise ValueError(message)

def identity(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

def grayscale(image, black, white, notes):
    if image.mode not in {'I', 'F', 'I;16', 'I;16L', 'I;16B'}:
        require(black is None and white is None, '--black/--white require high-bit-depth single-channel input.')
        return image
    if image.mode != 'F':
        image = image.convert('I')
    low, high = image.getextrema()
    require(math.isfinite(low) and math.isfinite(high), 'Non-finite pixels need an external decoder.')
    require((black is None) == (white is None), '--black and --white must be specified together.')
    low, high = (low, high) if black is None else (black, white)
    require(math.isfinite(low) and math.isfinite(high) and low <= high, 'Invalid display range.')
    notes.append({'grayscale_display_range': [low, high], 'measurement_preserving': False})
    if low == high:
        return Image.new('L', image.size, 0)
    return image.point(lambda value: (value - low) * (255.0 / (high - low))).convert('L')

def raw_input(path, args, notes):
    require(args.width is not None and args.height is not None, 'Raw input needs explicit --width and --height.')
    width, height = args.width, args.height
    require(width > 0 and height > 0 and width * height <= args.max_input_pixels, 'Raw geometry exceeds declared pixel limit.')
    bpp, layout = RAW_MODES[args.mode]
    row = width * bpp
    stride = row if args.stride is None else args.stride
    require(stride >= row and args.offset >= 0, 'Invalid stride or header offset.')
    required = args.offset + stride * height
    length = path.stat().st_size
    require(length >= required, 'Raw input is shorter than the explicit geometry.')
    require(args.allow_trailing or length == required, 'Trailing bytes: confirm geometry or specify --allow-trailing.')
    require(stride * height <= args.max_decode_bytes, 'Raw data exceeds --max-decode-bytes.')
    with path.open('rb') as stream:
        stream.seek(args.offset)
        data = stream.read(stride * height)
    require(len(data) == stride * height, 'Raw file truncated during read.')
    mode = 'RGB' if layout == 'BGR' else layout
    notes.append({'raw_layout': args.mode, 'stride': stride, 'offset': args.offset, 'demosaiced': False})
    return Image.frombytes(mode, (width, height), data, 'raw', layout, stride, 1)

def image_input(path, args, notes):
    if path.suffix.lower() in {'.heic', '.heif', '.hif'}:
        try:
            import pillow_heif
        except ImportError:
            raise ValueError('Phone format requires pillow-heif; run installer --extras.') from None
        pillow_heif.register_heif_opener()
    with Image.open(path) as image:
        require(image.width * image.height <= args.max_input_pixels, 'Image pixel limit exceeded.')
        require(args.frame < getattr(image, 'n_frames', 1), 'Frame/page index is outside this image.')
        image.seek(args.frame)
        notes.append({'selected_image_frame_zero_based': args.frame, 'decoded_mode': image.mode})
        return ImageOps.exif_transpose(image).copy()

def camera_input(path, args, notes):
    try:
        import rawpy
    except ImportError:
        raise ValueError('Camera raw requires rawpy; run installer --extras.') from None
    with rawpy.imread(str(path)) as raw:
        require(raw.sizes.width * raw.sizes.height <= args.max_input_pixels, 'Camera raw pixel limit exceeded.')
        pixels = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
    notes.append({'camera_render': 'half_size_camera_white_balance', 'measurement_preserving': False})
    return Image.fromarray(pixels)

def video_input(path, args, notes):
    require(args.time is not None and math.isfinite(args.time) and args.time >= 0, 'Video needs explicit nonnegative --time in seconds.')
    executable = shutil.which('ffmpeg')
    require(executable is not None, 'ffmpeg is required to decode video frames.')
    with tempfile.TemporaryDirectory(prefix='codex-image-proxy-frame-') as folder:
        frame = Path(folder) / 'frame.png'
        scale = f'scale={args.max_edge}:{args.max_edge}:force_original_aspect_ratio=decrease'
        result = subprocess.run([executable, '-nostdin', '-hide_banner', '-loglevel', 'error',
                                 '-ss', str(args.time), '-i', str(path), '-frames:v', '1',
                                 '-vf', scale, '-map_metadata', '-1', '-y', str(frame)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120,
                                **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
        require(result.returncode == 0 and frame.is_file(), 'Video decoder failed or no frame at timestamp.')
        require(frame.stat().st_size <= args.max_decode_bytes, 'Video intermediate exceeds decode byte limit.')
        with Image.open(frame) as image:
            require(image.width * image.height <= args.max_input_pixels, 'Video frame pixel limit exceeded.')
            output = image.copy()
    notes.append({'video_time_seconds': args.time, 'intermediate_max_edge': args.max_edge})
    return output

def encode_proxy(image, max_edge, max_bytes):
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    for _ in range(40):
        for quality in (85, 78, 70, 62, 54, 46, 38):
            buffer = BytesIO()
            image.save(buffer, format='JPEG', quality=quality, optimize=True,
                       progressive=True, exif=b'', icc_profile=None)
            data = buffer.getvalue()
            if len(data) <= max_bytes:
                return data, image.size, quality
        require(min(image.size) > 1, 'Unable to meet specified byte cap.')
        image = image.resize((max(1, int(image.width * .8)), max(1, int(image.height * .8))), Image.Resampling.LANCZOS)
    raise ValueError('Proxy size convergence failed.')

def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument('source', type=Path)
    value.add_argument('--output', type=Path, required=True)
    value.add_argument('--mode', choices=['auto', 'image', 'camera-raw', 'video', *RAW_MODES], default='auto')
    value.add_argument('--max-bytes', type=int, default=240000)
    value.add_argument('--max-edge', type=int, default=1600)
    value.add_argument('--max-input-pixels', type=int, default=160000000)
    value.add_argument('--max-decode-bytes', type=int, default=1024 * 1024 * 1024)
    value.add_argument('--crop', nargs=4, type=int, metavar=('X', 'Y', 'WIDTH', 'HEIGHT'))
    value.add_argument('--frame', type=int, default=0)
    value.add_argument('--time', type=float)
    value.add_argument('--width', type=int)
    value.add_argument('--height', type=int)
    value.add_argument('--offset', type=int, default=0)
    value.add_argument('--stride', type=int)
    value.add_argument('--allow-trailing', action='store_true')
    value.add_argument('--black', type=float)
    value.add_argument('--white', type=float)
    return value

def main(argv=None):
    args = parser().parse_args(argv)
    require(16000 <= args.max_bytes <= 500000, '--max-bytes must be in 16000..500000.')
    require(64 <= args.max_edge <= 2048, '--max-edge must be in 64..2048.')
    require(args.max_input_pixels > 0 and args.max_decode_bytes > 0 and args.frame >= 0, 'Invalid input limits or frame.')
    source = args.source.expanduser().resolve(strict=True)
    output = args.output.expanduser().absolute()
    require(source.is_file(), 'Source must be a regular file.')
    require(output.suffix.lower() in {'.jpg', '.jpeg'}, 'Proxy output needs .jpg or .jpeg suffix.')
    require(output.resolve() != source, 'Source overwrite rejected.')
    manifest = output.with_suffix(output.suffix + '.json')
    require(not output.exists() and not output.is_symlink() and not manifest.exists() and not manifest.is_symlink(), 'Output or metadata exists; choose a new path.')
    before = identity(source)
    Image.MAX_IMAGE_PIXELS = args.max_input_pixels
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    mode = args.mode
    if mode == 'auto':
        require(source.suffix.lower() not in {'.raw', '.bin'}, 'Raw geometry unspecified: give --mode and dimensions.')
        mode = 'camera-raw' if source.suffix.lower() in CAMERA else 'video' if source.suffix.lower() in VIDEOS else 'image'
    args.mode = mode
    notes = []
    if mode in RAW_MODES:
        image = raw_input(source, args, notes)
    elif mode == 'camera-raw':
        image = camera_input(source, args, notes)
    elif mode == 'video':
        require(args.crop is None, 'Video crop needs a separately extracted full source frame, not scaled coordinates.')
        image = video_input(source, args, notes)
    else:
        image = image_input(source, args, notes)
    original_size = image.size
    require(image.width * image.height <= args.max_input_pixels, 'Decoded image exceeds pixel limit.')
    if args.crop:
        x, y, width, height = args.crop
        require(x >= 0 and y >= 0 and width > 0 and height > 0 and x + width <= image.width and y + height <= image.height, 'Crop outside the oriented image.')
        image = image.crop((x, y, x + width, y + height))
    image = grayscale(image, args.black, args.white, notes)
    if 'A' in image.getbands() or 'transparency' in image.info:
        rgba = image.convert('RGBA')
        background = Image.new('RGBA', rgba.size, 'white')
        background.alpha_composite(rgba)
        image = background.convert('RGB')
        notes.append({'alpha_background': 'white'})
    else:
        image = image.convert('RGB')
    data, size, quality = encode_proxy(image, args.max_edge, args.max_bytes)
    require(identity(source) == before, 'Source changed during decode; proxy not published.')
    require(len(data) <= args.max_bytes, 'Encoded proxy exceeds byte cap.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        require(stream.write(data) == len(data), 'Short proxy write.')
        stream.flush()
        os.fsync(stream.fileno())
    require(output.stat().st_size == len(data), 'Proxy file size mismatch.')
    metadata = {'proxy_path': str(output), 'metadata_path': str(manifest), 'source_path': str(source),
                'source_bytes': before[2], 'decoded_dimensions': list(original_size), 'crop': args.crop,
                'proxy_dimensions': list(size), 'output_bytes': len(data), 'max_bytes': args.max_bytes,
                'quality': quality, 'encoded_base64_bytes': 4 * ((len(data) + 2) // 3),
                'proxy_sha256': hashlib.sha256(data).hexdigest(),
                'mode': mode, 'notes': notes, 'original_modified': False}
    with manifest.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(metadata, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'error': str(error), 'error_type': type(error).__name__, 'proxy_ready': False}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
