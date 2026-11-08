# Third-party notices

The project's own source, skill instructions, installers and documentation are
available under the MIT License, copyright (c) 2026 FrankeyLing. This does not
replace third-party copyright or license terms.

## Image codecs

Unmodified stb headers are pinned to commit
`2b2e64bc4778df6a06fbea3a5dbe61f7a76ecf19`. Their original dual MIT/public-domain
license is retained in `image-proxy-first/native/vendor/LICENSE` and inside
the headers. Source URLs and hashes are in `native/dependencies.json`.

## Precompiled runtime components

The binaries were built with Zig 0.17.1. Runtime components may be statically
linked into the precompiled files. Original notices are included under
`image-proxy-first/native/licenses/`:

| Component | Included notice |
| --- | --- |
| Zig/runtime support | Zig-LICENSE |
| libc++ | libcxx-LICENSE.TXT |
| libc++abi | libcxxabi-LICENSE.TXT |
| LLVM unwinder | libunwind-LICENSE.TXT |
| musl C library (Linux targets) | musl-COPYRIGHT |
| MinGW-w64 (Windows targets) | mingw-COPYING |

The full compiler is not distributed. `licenses/provenance.json` records the
original distribution paths and digests of these notices. Additional notices
embedded in the upstream source files remain intact.

## Optional dependencies

Pillow, pillow-heif, rawpy and ffmpeg are not bundled. If installed separately
for fallback decoding, they retain their own licenses. The normal native path
does not require them.
