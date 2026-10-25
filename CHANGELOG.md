# Changelog

All notable changes are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: semver.

## [Unreleased]

### Added
- Source-only public staging tree (`v0.1.0`): host governed agent runtime,
  device iOS runtime, offline unit test suite, architecture and security docs.
- **ZTako product identity and showcase** (commits `7b020d3`, `613c555`, `0268e73`):
  - Bilingual static showcase website (`website/`, English + 简体中文) published
    via GitHub Pages with a dedicated deploy workflow (`deploy-website.yml`);
    V3 rebuilt the site around the task experience: hero task demo, interactive
    task zone with confirm/cancel authorization concepts, background planning
    visualization, agent anatomy, screenshot-to-action demo, personal-Jarvis
    direction and a compact engineering strip. All demos are labeled concept
    demos; no product source was changed by the website work.
  - Bilingual customer-facing `README.md` / `README.zh-CN.md`, with the previous
    technical README preserved at `docs/PROJECT-TECHNICAL.md`.

### Changed
- License status: the root license review concluded — project-owned source is
  licensed **Apache-2.0** (`LICENSE`). This supersedes the earlier
  "root license pending review" wording (see `DEPENDENCIES.md` for third-party
  components, which keep their own licenses).

### Verified
- The public offline host suite currently counts **74 tests, all passing**,
  verified locally on the public tree at `0268e73` (2026-10-26; offline, no
  device and no credentials) and green in CI on every push. The historical
  70/70 figure refers to commit `98b965e` (CI run of 2026-10-02). Four visual
  domain tests were added on top of the public synthetic benchmark fixtures in
  `testdata/` (see issue #5 for the remaining coverage gap).

### Notes
- The project remains **pre-release**; no official binary release, device
  feature claims, or production deployment are represented by this changelog.
- Third-party components are intentionally not vendored; see `DEPENDENCIES.md`.
