# Changelog

## 1.1.2 - 2026-05-11
### Added
- Hash cache: perceptual hashes are stored in the database after the first scan and reused on subsequent runs — only new or changed files are re-hashed, making re-scans of large libraries (400 GB+) dramatically faster
- BK-tree comparison: replaced the O(n^2) pairwise hash comparison with an O(n log n) BK-tree nearest-neighbour search, reducing the grouping phase from hours to seconds for large libraries

### Fixed
- HEIC/HEIF photos (iPhone) now supported via pillow-heif — previously skipped silently
- Very large images (>89 MP) no longer crash the scanner (PIL decompression bomb limit raised to 300 MP)
- Scan completion notification now uses the internal container URL instead of the external Cloudflare domain, fixing broken notifications


## 1.1.1 - 2026-05-10
### Fixed
- Nextcloud 33 compatibility: replace removed OC_App::getAppPath() and OC::$server->getConfig() with supported NC33 APIs
- App now boots correctly on Nextcloud 33.x without crashing every request


## 1.1.0 - 2026-03-30
### Added
- Perceptual hash duplicate detection (dHash, pHash, wHash)
- Bulk delete with glob filter patterns
- Protection rules for folders
- Audit log with CSV export
- Inline image preview lightbox
- Scan progress polling

### Fixed
- Filter pattern correctly applied during bulk delete
- Group cleanup respects active filter
