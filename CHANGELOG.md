# Changelog

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
