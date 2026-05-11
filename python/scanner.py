"""
scanner.py — walks Nextcloud file storage, hashes images/videos, finds duplicates.
Writes results to oc_ud_groups and oc_ud_group_files.

Performance features:
  - Hash cache: computed hashes are stored in oc_ud_hash_cache and reused on
    subsequent scans as long as the file has not changed (checked via mtime).
    Re-scanning a 400 GB library after the first run only re-hashes new/changed files.
  - BK-tree: replaces the O(n^2) pairwise comparison with an O(n log n)
    nearest-neighbour search under Hamming distance.
"""
import os
import time
import urllib.request
import urllib.parse
import logging
from PIL import Image, ImageOps
import PIL
# Raise decompression bomb limit to handle very large photos (default 89 MP is too low)
PIL.Image.MAX_IMAGE_PIXELS = 300_000_000
# Register HEIC/HEIF support via pillow-heif if available
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass
import imagehash
import db

log = logging.getLogger('ud_scanner')

IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp',
               'image/tiff', 'image/bmp', 'image/heic', 'image/heif'}
VIDEO_MIMES = {'video/mp4', 'video/avi', 'video/mkv', 'video/mov',
               'video/quicktime', 'video/x-msvideo', 'video/webm',
               'video/mpeg', 'video/3gpp'}


# ---------------------------------------------------------------------------
# BK-tree for O(n log n) similarity search under Hamming distance
# ---------------------------------------------------------------------------

class BKTree:
    """
    BK-tree over perceptual hashes using Hamming distance as the metric.

    Each node stores: [hash_val, [item, ...], {distance: child_node}]
    Items with identical hashes share the same node (exact duplicates).
    """

    def __init__(self):
        self._root = None

    def add(self, hash_val, item):
        if self._root is None:
            self._root = [hash_val, [item], {}]
            return
        node = self._root
        while True:
            d = node[0] - hash_val          # Hamming distance (imagehash int)
            if d == 0:
                node[1].append(item)        # exact duplicate hash
                return
            children = node[2]
            if d not in children:
                children[d] = [hash_val, [item], {}]
                return
            node = children[d]

    def search(self, hash_val, threshold):
        """Return list of items whose hash is within *threshold* Hamming distance."""
        if self._root is None:
            return []
        results = []
        stack = [self._root]
        while stack:
            node = stack.pop()
            d = node[0] - hash_val
            if d <= threshold:
                results.extend(node[1])
            low  = d - threshold
            high = d + threshold
            for child_d, child in node[2].items():
                if low <= child_d <= high:
                    stack.append(child)
        return results


# ---------------------------------------------------------------------------
# Hash cache  (oc_ud_hash_cache)
# ---------------------------------------------------------------------------

def _ensure_cache_table():
    """Create the hash-cache table if it does not exist yet."""
    try:
        db.execute(
            '''CREATE TABLE IF NOT EXISTS oc_ud_hash_cache (
                fileid     BIGINT       NOT NULL,
                mtime      INT          NOT NULL,
                hash_algo  VARCHAR(20)  NOT NULL,
                hash_size  SMALLINT     NOT NULL,
                hash_value VARCHAR(256) NOT NULL,
                PRIMARY KEY (fileid, hash_algo, hash_size)
            )'''
        )
    except Exception as e:
        log.warning('Could not create hash cache table: %s', e)


def _get_cached_hash(fileid, mtime, algo, hash_size):
    """Return cached ImageHash if the file has not changed, else None."""
    try:
        row = db.fetchone(
            'SELECT hash_value, mtime FROM oc_ud_hash_cache'
            ' WHERE fileid=%s AND hash_algo=%s AND hash_size=%s',
            (fileid, algo, hash_size)
        )
        if row and int(row['mtime']) == int(mtime):
            return imagehash.hex_to_hash(row['hash_value'])
    except Exception:
        pass
    return None


def _store_cached_hash(fileid, mtime, algo, hash_size, h):
    """Upsert a hash into the cache."""
    try:
        db.execute(
            '''INSERT INTO oc_ud_hash_cache
                   (fileid, mtime, hash_algo, hash_size, hash_value)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE mtime=%s, hash_value=%s''',
            (fileid, mtime, algo, hash_size, str(h), mtime, str(h))
        )
    except Exception as e:
        log.warning('Could not store hash cache entry: %s', e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_hash_fn(algo: str):
    algos = {
        'dhash':   imagehash.dhash,
        'phash':   imagehash.phash,
        'whash':   imagehash.whash,
        'average': imagehash.average_hash,
    }
    return algos.get(algo, imagehash.dhash)


def hamming(h1, h2) -> int:
    return h1 - h2


def get_nc_file_path(fileid: int, datadir: str):
    row = db.fetchone(
        '''SELECT fc.path, s.id as storage_id
           FROM oc_filecache fc
           JOIN oc_storages s ON s.numeric_id = fc.storage
           WHERE fc.fileid = %s''',
        (fileid,)
    )
    if not row:
        return None
    storage_id = row['storage_id']
    rel_path   = row['path']
    if storage_id.startswith('local::'):
        base = storage_id[7:]
        full = os.path.join(base, rel_path)
        if os.path.exists(full):
            return full
    if storage_id.startswith('home::'):
        user = storage_id[6:]
        full = os.path.join(datadir, user, 'files', rel_path.replace('files/', '', 1))
        if os.path.exists(full):
            return full
        full2 = os.path.join(datadir, user, rel_path)
        if os.path.exists(full2):
            return full2
    return None


def get_target_files(task_settings: dict) -> list:
    target_dir_ids = task_settings['target_directory_ids']
    target_mtype   = task_settings['target_mtype']
    datadir        = db.get_config()['datadir']

    if target_mtype == 0:
        mime_parts = ('image',)
    elif target_mtype == 1:
        mime_parts = ('video',)
    else:
        mime_parts = ('image', 'video')

    files   = []
    visited = set()

    def scan_dir(fileid):
        if fileid in visited:
            return
        visited.add(fileid)
        children = db.fetchall(
            '''SELECT fc.fileid, fc.name, fc.path, fc.size, fc.mtime,
                      m.mimetype  AS mime_str,
                      mp.mimetype AS mime_part,
                      s.id        AS storage_id
               FROM oc_filecache fc
               JOIN oc_mimetypes m  ON m.id  = fc.mimetype
               JOIN oc_mimetypes mp ON mp.id = fc.mimepart
               JOIN oc_storages  s  ON s.numeric_id = fc.storage
               WHERE fc.parent = %s''',
            (fileid,)
        )
        for child in children:
            mime_part = child['mime_part']
            mime_str  = child['mime_str']
            if mime_part == 'httpd/unix-directory' or mime_str == 'httpd/unix-directory':
                scan_dir(child['fileid'])
            elif mime_part in mime_parts:
                storage_id = child['storage_id']
                rel_path   = child['path']
                disk_path  = None
                if storage_id.startswith('local::'):
                    p = os.path.join(storage_id[7:], rel_path)
                    if os.path.exists(p):
                        disk_path = p
                elif storage_id.startswith('home::'):
                    user = storage_id[6:]
                    p = os.path.join(datadir, user, rel_path)
                    if os.path.exists(p):
                        disk_path = p
                if disk_path:
                    files.append({
                        'fileid':    child['fileid'],
                        'filename':  child['name'],
                        'filepath':  os.path.dirname(child['path']),
                        'filesize':  child['size'],
                        'mtime':     child['mtime'],
                        'mimetype':  mime_str,
                        'mime_part': mime_part,
                        'disk_path': disk_path,
                    })

    for dir_id in target_dir_ids:
        scan_dir(int(dir_id))

    return files


def hash_image(disk_path: str, algo: str, hash_size: int, exif_transpose: bool):
    try:
        img = Image.open(disk_path)
        if exif_transpose:
            img = ImageOps.exif_transpose(img)
        img = img.convert('RGB')
        return get_hash_fn(algo)(img, hash_size=hash_size)
    except Exception as e:
        log.warning('Failed to hash image %s: %s', disk_path, e)
        return None


def hash_video(disk_path, algo, hash_size):
    import subprocess, tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp_path = tmp.name
        for seek in ['1', '0']:
            r = subprocess.run(
                ['ffmpeg', '-y', '-ss', seek, '-i', disk_path,
                 '-frames:v', '1', '-q:v', '2', tmp_path],
                capture_output=True, timeout=30
            )
            if r.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                break
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            img = Image.open(tmp_path).convert('RGB')
            h   = get_hash_fn(algo)(img, hash_size=hash_size)
            os.unlink(tmp_path)
            return h
    except Exception as e:
        log.warning('Failed to hash video %s: %s', disk_path, e)
    return None


# ---------------------------------------------------------------------------
# Core duplicate-finder  (BK-tree + hash cache)
# ---------------------------------------------------------------------------

def find_duplicates(files: list, task_settings: dict) -> list:
    """
    Hash every file (using the cache where possible), build a BK-tree, then
    perform an O(n log n) nearest-neighbour search to group duplicates.
    """
    algo      = task_settings['hashing_algorithm']
    hash_size = task_settings['hash_size']
    threshold = task_settings['precision']
    exif      = task_settings['exif_transpose']
    task_id   = task_settings['id']

    _ensure_cache_table()

    tree       = BKTree()
    hashed     = []       # [(ImageHash, file_dict)]  — kept for iteration order
    total      = len(files)
    cache_hits = 0

    log.info('Hashing %d files (algo=%s, hash_size=%d, threshold=%d)',
             total, algo, hash_size, threshold)

    for i, f in enumerate(files):
        fileid = f['fileid']
        mtime  = f.get('mtime', 0)
        h      = None

        # 1. Try cache first
        h = _get_cached_hash(fileid, mtime, algo, hash_size)
        if h is not None:
            cache_hits += 1
        else:
            # 2. Compute hash from disk
            if f['mime_part'] == 'image':
                h = hash_image(f['disk_path'], algo, hash_size, exif)
            elif f['mime_part'] == 'video':
                h = hash_video(f['disk_path'], algo, hash_size)

            if h is not None:
                _store_cached_hash(fileid, mtime, algo, hash_size, h)

        if h is not None:
            hashed.append((h, f))
            tree.add(h, f)

        # Update progress every 50 files
        if (i + 1) % 50 == 0 or i == total - 1:
            db.execute(
                'UPDATE oc_ud_tasks SET files_scanned = %s WHERE id = %s',
                (i + 1, task_id)
            )

    pct = 100 * cache_hits / total if total else 0
    log.info('Hashing done — cache hits: %d/%d (%.0f%%)', cache_hits, total, pct)

    # BK-tree grouping — O(n log n)
    log.info('Building duplicate groups from %d hashed files via BK-tree...', len(hashed))
    used   = set()   # fileids already assigned to a group
    groups = []

    for h, f in hashed:
        fid = f['fileid']
        if fid in used:
            continue
        neighbors = tree.search(h, threshold)
        group = [n for n in neighbors if n['fileid'] not in used]
        if len(group) >= 2:
            groups.append(group)
            for n in group:
                used.add(n['fileid'])

    log.info('Found %d duplicate groups', len(groups))
    return groups


# ---------------------------------------------------------------------------
# Save results & task entry point
# ---------------------------------------------------------------------------

def save_results(task_id: int, groups: list):
    db.execute('DELETE FROM oc_ud_group_files WHERE task_id = %s', (task_id,))
    db.execute('DELETE FROM oc_ud_groups     WHERE task_id = %s', (task_id,))
    for group_id, group in enumerate(groups, start=1):
        db.execute(
            'INSERT INTO oc_ud_groups (task_id, group_id, hash) VALUES (%s, %s, %s)',
            (task_id, group_id, '')
        )
        for f in group:
            db.execute(
                '''INSERT INTO oc_ud_group_files
                       (task_id, group_id, fileid, filename, filepath, filesize)
                   VALUES (%s, %s, %s, %s, %s, %s)''',
                (task_id, group_id, f['fileid'], f['filename'], f['filepath'], f['filesize'])
            )
    log.info('Saved %d duplicate groups for task %d', len(groups), task_id)


def run_task(task_id: int):
    log.info('Starting scan task %d', task_id)
    import json

    task = db.fetchone('SELECT * FROM oc_ud_tasks WHERE id = %s', (task_id,))
    if not task:
        log.error('Task %d not found', task_id)
        return

    collector_settings = json.loads(task['collector_settings']) if isinstance(task['collector_settings'], str) else task['collector_settings']
    target_dir_ids     = json.loads(task['target_directory_ids']) if isinstance(task['target_directory_ids'], str) else task['target_directory_ids']

    hash_size     = int(collector_settings.get('hash_size', 16))
    sim_threshold = int(collector_settings.get('similarity_threshold', 90))
    num_bits      = hash_size ** 2
    if sim_threshold == 100:
        precision = int(hash_size / 8)
    else:
        precision = num_bits - int(round(num_bits / 100.0 * sim_threshold))
        if precision == 0:
            precision = 1

    task_settings = {
        'id':                   task_id,
        'target_directory_ids': target_dir_ids,
        'target_mtype':         int(collector_settings.get('target_mtype', 2)),
        'hashing_algorithm':    collector_settings.get('hashing_algorithm', 'dhash'),
        'hash_size':            hash_size,
        'precision':            precision,
        'exif_transpose':       bool(collector_settings.get('exif_transpose', True)),
    }

    db.execute(
        'UPDATE oc_ud_tasks SET py_pid = %s, files_scanned = 0, errors = %s WHERE id = %s',
        (os.getpid(), '', task_id)
    )

    try:
        log.info('Scanning directories: %s', target_dir_ids)
        files = get_target_files(task_settings)
        log.info('Found %d files to scan', len(files))

        db.execute(
            'UPDATE oc_ud_tasks SET files_total = %s WHERE id = %s',
            (len(files), task_id)
        )

        if not files:
            log.warning('No files found for task %d', task_id)
            db.execute(
                'UPDATE oc_ud_tasks SET finished_time = %s, py_pid = 0 WHERE id = %s',
                (int(time.time()), task_id)
            )
            return

        groups = find_duplicates(files, task_settings)
        save_results(task_id, groups)

        db.execute(
            'UPDATE oc_ud_tasks SET finished_time = %s, py_pid = 0, files_scanned = %s WHERE id = %s',
            (int(time.time()), len(files), task_id)
        )
        log.info('Task %d completed successfully', task_id)

        # Send Nextcloud notification if enabled
        try:
            secret   = db.get_app_value('urbanduplicati', 'internal_secret', '')
            base_url = 'http://localhost'  # always use internal URL; overwrite.cli.url is the external Cloudflare URL
            if secret:
                url  = base_url.rstrip('/') + '/index.php/apps/urbanduplicati/api/v1/notify/' + str(task_id)
                data = urllib.parse.urlencode({'secret': secret}).encode()
                req  = urllib.request.Request(url, data=data, method='POST')
                req.add_header('OCS-APIREQUEST', 'true')
                urllib.request.urlopen(req, timeout=10)
                log.info('Notification sent for task %d', task_id)
        except Exception as ne:
            log.warning('Could not send notification for task %d: %s', task_id, ne)

    except Exception as e:
        log.exception('Task %d failed: %s', task_id, e)
        db.execute(
            'UPDATE oc_ud_tasks SET errors = %s, py_pid = 0, finished_time = %s WHERE id = %s',
            (str(e)[:500], int(time.time()), task_id)
        )
