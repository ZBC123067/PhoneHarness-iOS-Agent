# Third-Party Notices

This tree contains **project-owned source only**. No third-party source, static
library, or binary is vendored here, so nothing in-tree is relicensed under the
project's Apache-2.0 license.

## Referenced, not bundled

| Component | Referenced by | License |
|---|---|---|
| ldid | `mcp-ldid/` build | AGPL-3.0-only |
| AppSync Unified / appinst | `mcp-roothelper/` build | GPL-3.0-or-later |
| OpenSSL libcrypto | `mcp-ldid/` build | Apache-2.0 |
| libplist | `mcp-ldid/` build | LGPL-2.1-or-later |
| libzip | helper tools | BSD-3-Clause |
| Theos / Logos | build system | own terms |
| MobileSubstrate / ElleKit | runtime injection | own terms |
| PreferenceLoader | preferences bundle | own terms |
| roothide library | roothide builds | own terms |

The project's Apache-2.0 license applies to PhoneHarness-owned code only. These
components are **not** covered by it and are **not** relicensed here.

## Boundary for binary distribution

> Source-code licensing of PhoneHarness under Apache-2.0 does not imply that a
> future binary distribution combining these external copyleft dependencies can
> be redistributed under Apache-2.0 alone. Any future `.deb` / binary release
> requires a separate dependency and license review.

## Obligations if you redistribute

1. Keep this file, `NOTICE`, and `LICENSE` with any distribution.
2. Preserve copyright and license notices of the components you add back.
3. If you re-introduce a GPL/AGPL/LGPL component, provide the corresponding
   source and satisfy that license's relink/source obligations.

This is an engineering compliance summary, not legal advice.
