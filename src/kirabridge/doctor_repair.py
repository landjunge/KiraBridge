"""Restricted doctor repair: isolated launcher permission restoration only."""
from __future__ import annotations

import os
import stat
import hashlib
import hmac
import json
from pathlib import Path


def repair_launcher_permissions(path: Path, *, approve: bool = False) -> dict:
    """Restore owner execute bit on an existing owner-controlled regular launcher.

    Never follows symlinks, creates files, changes owner, or touches daemon state.
    """
    if not approve:
        return {"status": "approval_required", "changed": False}
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            return {"status": "unsafe_target", "changed": False}
        before = stat.S_IMODE(info.st_mode)
        after = before | stat.S_IXUSR
        if before == after:
            return {"status": "already_ok", "changed": False}
        # No write until the exact target and original mode are recorded.
        os.fchmod(fd, after)
        return {"status": "repaired", "changed": True, "before_mode": oct(before), "after_mode": oct(after), "rollback_mode": oct(before), "target_path": str(path.resolve()), "target_dev": info.st_dev, "target_ino": info.st_ino, "target_sha256": hashlib.sha256(os.pread(fd, info.st_size, 0)).hexdigest() if info.st_size <= 1048576 else None}
    finally:
        os.close(fd)


def rollback_launcher_permissions(path: Path, *, expected_mode: int, original_mode: int, approve: bool = False) -> dict:
    """Restore recorded mode only if the launcher still has the expected mode."""
    if not approve:
        return {"status": "approval_required", "changed": False}
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            return {"status": "unsafe_target", "changed": False}
        current = stat.S_IMODE(info.st_mode)
        if current != expected_mode:
            return {"status": "changed_since_repair", "changed": False}
        if original_mode & ~0o777 or expected_mode & ~0o777:
            return {"status": "invalid_mode", "changed": False}
        os.fchmod(fd, original_mode)
        return {"status": "rolled_back", "changed": True, "mode": oct(original_mode)}
    finally:
        os.close(fd)


def _private_receipt_directory(path: Path) -> None:
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('receipt directory must be owner-only')


def _receipt_key(path: Path) -> bytes:
    _private_receipt_directory(path)
    key_path = path.with_name(path.name + '.key')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(key_path, flags)
    except FileNotFoundError:
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(os.urandom(32))
            output.flush()
            os.fsync(output.fileno())
        fd = os.open(key_path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('unsafe receipt key')
        key = os.read(fd, 33)
        if len(key) != 32:
            raise ValueError('invalid receipt key')
        return key
    finally:
        os.close(fd)


def _receipt_key_existing(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('unsafe receipt key')
        key = os.read(fd, 33)
        if len(key) != 32:
            raise ValueError('invalid receipt key')
        return key
    finally:
        os.close(fd)


def _receipt_mac(record: dict, key: bytes) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def save_repair_receipt(path: Path, receipt: dict) -> dict:
    """Create one owner-only immutable repair receipt; refuse replacement and symlinks."""
    import json
    allowed = {'status', 'changed', 'before_mode', 'after_mode', 'rollback_mode', 'target_path', 'target_dev', 'target_ino', 'target_sha256'}
    record = {key: receipt[key] for key in allowed if key in receipt}
    if record.get('status') != 'repaired' or record.get('changed') is not True:
        return {'status': 'not_a_repair', 'saved': False}
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
    _private_receipt_directory(path)
    key = _receipt_key(path)
    record['integrity_hmac'] = _receipt_mac(record, key)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(record, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {'status': 'saved', 'saved': True}


def rollback_from_receipt(path: Path, receipt_path: Path, *, approve: bool = False) -> dict:
    """Rollback using private recorded modes, not user-supplied mode values."""
    import json
    if not approve:
        return {'status': 'approval_required', 'changed': False}
    fd = os.open(receipt_path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            return {'status': 'unsafe_receipt', 'changed': False}
        with os.fdopen(fd, 'r', encoding='utf-8') as source:
            fd = -1
            record = json.load(source)
    finally:
        if fd >= 0:
            os.close(fd)
    tag = record.pop('integrity_hmac', None)
    try:
        _private_receipt_directory(receipt_path)
    except (OSError, ValueError):
        return {'status': 'unsafe_receipt_directory', 'changed': False}
    key_path = receipt_path.with_name(receipt_path.name + '.key')
    try:
        key = _receipt_key_existing(key_path)
    except (OSError, ValueError):
        return {'status': 'integrity_unavailable', 'changed': False}
    if not isinstance(tag, str) or not hmac.compare_digest(tag, _receipt_mac(record, key)):
        return {'status': 'integrity_failed', 'changed': False}
    if record.get('status') != 'repaired' or record.get('changed') is not True:
        return {'status': 'invalid_receipt', 'changed': False}
    try:
        before = int(record['before_mode'], 8)
        after = int(record['after_mode'], 8)
    except (KeyError, ValueError, TypeError):
        return {'status': 'invalid_receipt', 'changed': False}
    if not all(key in record for key in ('target_path', 'target_dev', 'target_ino', 'target_sha256')):
        return {'status': 'unbound_receipt', 'changed': False}
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            return {'status': 'unsafe_target', 'changed': False}
        digest = hashlib.sha256(os.pread(fd, info.st_size, 0)).hexdigest() if info.st_size <= 1048576 else None
        if str(path.resolve()) != record['target_path'] or info.st_dev != record['target_dev'] or info.st_ino != record['target_ino'] or digest != record['target_sha256'] or digest is None:
            return {'status': 'target_mismatch', 'changed': False}
    finally:
        os.close(fd)
    return rollback_launcher_permissions(path, expected_mode=after, original_mode=before, approve=True)
