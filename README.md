# image-proxy-first

A global Codex skill for inspecting large images through small proxies. A
precompiled C++ tool prepares the images and metadata in one command; the
next tool call views only the proxies you need. Original image bytes and
base64 are never printed to tool text.

[中文说明](README.zh-CN.md) · [Download releases](https://github.com/FrankeyLing/image-proxy-first/releases)

## Install

Download and extract the portable ZIP from Releases, or clone this repository.

- **Windows:** double-click `INSTALL.cmd`.
- **Ubuntu/Linux:** run `bash install.sh`.
- **Update an existing installation:** use `install.ps1 -ReplaceExisting` on
  Windows or `bash install.sh --replace-existing` on Linux. The old skill is
  retained under the user's Codex `skill-backups` directory.

The installer selects a bundled x64 or ARM64 binary for Windows or Linux.
Normal installation and image preparation require no Python, compiler,
administrator rights or dependency downloads. The default destination is
`~/.codex/skills/image-proxy-first`; `CODEX_HOME` is respected. Start a new
Codex chat or reload skills after installation if needed.

## One preparation command

Use the installed `scripts/proxy.cmd` on Windows or `scripts/proxy` on Linux:

```text
proxy photo.jpg
proxy first.jpg second.png --preset fast
proxy screenshot.png --preset text --layout halves
proxy screenshot.png --preset detail --layout grid
proxy long-screenshot.png --layout strips
proxy photo.jpg --crop 100 200 1800 900
```

Omit `--out-dir` to create a unique temporary directory automatically. An
explicit output directory must be new. Image decoding, orientation, crop
coordinates, resizing, compression, byte-cap verification and common cuts
are handled inside the program. Metadata includes paths, dimensions,
source crop boxes, byte counts, timings and executable argument arrays for
alternative recipes. It contains no image payload.

After preparation, pass only selected `items[].proxies[].path` values to the
image viewer. If multiple images are needed, batch that viewing operation.
Do not send every prepared tile automatically. The ordinary workflow takes
two model tool calls once the skill is loaded.

| Preset | Maximum bytes per proxy | Maximum edge | Default cuts |
| --- | ---: | ---: | --- |
| fast | 96,000 | 1280 pixels | overview |
| balanced | 240,000 | 1600 pixels | overview and overlapping halves when useful |
| text | 240,000 | 1600 pixels | overview and overlapping halves |
| detail | 300,000 | 2048 pixels | overview and four details |

`--layout` also accepts `overview`, `halves`, `grid`, `strips`, and `all`.
The absolute per-file cap is 500,000 bytes. Compression can reduce pixel
dimensions further to meet that cap. Originals are never modified. Small
text can be inspected by cropping the original locally and producing
another capped proxy.

## Formats and fallback

The native path supports common photos and bitmaps, the first frame of
supported animated formats, and explicitly described 8/16-bit industrial
buffers. Raw geometry, channel order, byte order and row stride must not be
guessed. See [format details](image-proxy-first/references/formats.md).

Unsupported codecs automatically use the Python fallback within the same
preparation command. Optional fallback setup requires an existing Python
3.10+ and internet for dependencies:

```text
# Windows, run in PowerShell
.\install.ps1 -WithPythonFallback
.\install.ps1 -ReplaceExisting -Extras

# Linux
bash install.sh --with-python-fallback
bash install.sh --replace-existing --extras
```

`Extras` adds phone high-efficiency and camera-raw decoders. Video extraction
additionally requires ffmpeg on PATH. Missing dependencies produce a clear
error; the native path does not install or compile anything at first use.

## Build, validation and limitations

Full project source and pinned third-party headers are included. See
[build instructions](image-proxy-first/native/BUILD.md),
[binary digests](image-proxy-first/native/builds.json) and
[synthetic benchmark results](image-proxy-first/native/test-report.json).

Windows x64 was tested locally. The other bundled targets were cross-compiled
and their executable formats checked; that does not constitute a target
runtime test. Linux binaries are statically linked. Benchmarks use synthetic
local files and warm caches, and do not guarantee latency on other systems.

This skill is agent guidance and a local program, not a network interception
plugin. It cannot retroactively compress attachments already sent directly
to a chat. Proxy size does not bound decoding memory. Proxies may lose small
text, color fidelity, bit depth and measurement detail; they are not a
replacement for numerical analysis of original pixels.

## License

Project-owned code and documentation: **MIT**, copyright © 2026 FrankeyLing.
Third-party headers and compiled runtime components retain their original
licenses. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).
