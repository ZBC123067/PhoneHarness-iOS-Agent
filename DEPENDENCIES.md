# Dependencies

PhoneHarness is distributed as **project-owned source only**. No third-party
source, prebuilt static library, or binary is vendored in this tree.

## External build/runtime dependencies (not vendored)

| Dependency | Needed by | License | Notes |
|---|---|---|---|
| Theos / Logos | building the tweak | own terms | install separately |
| MobileSubstrate / ElleKit | runtime injection | own terms | package dependency |
| PreferenceLoader | preferences bundle | own terms | runtime package dependency |
| roothide library | roothide builds | own terms | linked only for the roothide scheme |
| ldid | `mcp-ldid` helper | AGPL-3.0-only | strong copyleft — **not vendored** |
| AppSync Unified / appinst | `mcp-roothelper` zip shim | GPL-3.0-or-later | strong copyleft — **not vendored** |
| OpenSSL libcrypto | `mcp-ldid` build | Apache-2.0 | permissive |
| libplist | `mcp-ldid` build | LGPL-2.1-or-later | copyleft (LGPL) when statically linked |
| libzip | helper tools | BSD-3-Clause | permissive |
| zlib, libxml2, iconv | helper tools | own terms | platform/SDK libraries |

Because the helper tools (`mcp-ldid`, `mcp-roothelper`) depend on
strong-copyleft sources, they are **deliberately excluded** from this public tree.
Their `Makefile`s remain so the dependency is explicit; each one **fails fast
with setup instructions** if the external source is absent, and never downloads,
builds, or relicenses third-party code on its own.

## Root license

Project-owned code is licensed **Apache-2.0** (`LICENSE`). This is limited to
PhoneHarness-owned code: project-owned sources carry no third-party copyright
headers, and no project-owned file was found to be a derivative, modified copy,
or incorporated source of ldid, AppSync, libplist, or other copyleft code.

### Explicit boundary

> Source-code licensing of PhoneHarness under Apache-2.0 does **not** imply that
> future binary distributions combining external copyleft dependencies (such as
> ldid / AGPL-3.0, AppSync / GPL-3.0, or statically linked libplist / LGPL-2.1)
> can be redistributed under Apache-2.0 alone.

Any future `.deb` or other binary release requires a **separate dependency and
license review**. Excluded and external components keep their own licenses and
must not be relabelled.
