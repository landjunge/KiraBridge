import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

from kirabridge.doctor_repair import repair_launcher_permissions


def test_approval_and_rollback_metadata():
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'kirabridge'
        path.write_text('#!/bin/sh\n')
        path.chmod(0o600)
        assert repair_launcher_permissions(path)['status'] == 'approval_required'
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        result = repair_launcher_permissions(path, approve=True)
        assert result['status'] == 'repaired'
        assert result['rollback_mode'] == '0o600'
        assert os.access(path, os.X_OK)
        assert repair_launcher_permissions(path, approve=True)['status'] == 'already_ok'


def test_symlink_rejected():
    with TemporaryDirectory() as directory:
        target = Path(directory) / 'target'
        target.write_text('test')
        link = Path(directory) / 'link'
        link.symlink_to(target)
        try:
            repair_launcher_permissions(link, approve=True)
        except OSError:
            pass
        else:
            raise AssertionError('symlink was accepted')


def test_rollback_and_changed_file_refusal():
    from kirabridge.doctor_repair import rollback_launcher_permissions
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'kirabridge'
        path.write_text('#!/bin/sh\n')
        path.chmod(0o600)
        repair_launcher_permissions(path, approve=True)
        assert rollback_launcher_permissions(path, expected_mode=0o700, original_mode=0o600)['status'] == 'approval_required'
        path.chmod(0o744)
        assert rollback_launcher_permissions(path, expected_mode=0o700, original_mode=0o600, approve=True)['status'] == 'changed_since_repair'
        path.chmod(0o700)
        assert rollback_launcher_permissions(path, expected_mode=0o700, original_mode=0o600, approve=True)['status'] == 'rolled_back'
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_missing_file_refused():
    from kirabridge.doctor_repair import rollback_launcher_permissions
    with TemporaryDirectory() as directory:
        missing = Path(directory) / 'missing'
        for operation in (
            lambda: repair_launcher_permissions(missing, approve=True),
            lambda: rollback_launcher_permissions(missing, expected_mode=0o700, original_mode=0o600, approve=True),
        ):
            try:
                operation()
            except FileNotFoundError:
                pass
            else:
                raise AssertionError('missing file was accepted')


def test_directory_refused():
    from kirabridge.doctor_repair import rollback_launcher_permissions
    with TemporaryDirectory() as directory:
        path = Path(directory)
        assert repair_launcher_permissions(path, approve=True)['status'] == 'unsafe_target'
        assert rollback_launcher_permissions(path, expected_mode=0o700, original_mode=0o600, approve=True)['status'] == 'unsafe_target'


def test_invalid_mode_does_not_modify():
    from kirabridge.doctor_repair import rollback_launcher_permissions
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'launcher'
        path.write_text('test')
        path.chmod(0o700)
        assert rollback_launcher_permissions(path, expected_mode=0o700, original_mode=0o1000, approve=True)['status'] == 'invalid_mode'
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_receipt_is_owner_only_and_not_overwritten():
    from kirabridge.doctor_repair import save_repair_receipt
    with TemporaryDirectory() as directory:
        receipt = Path(directory) / 'receipt.json'
        data = {'status':'repaired','changed':True,'before_mode':'0o600','after_mode':'0o700','rollback_mode':'0o600','secret':'omit'}
        assert save_repair_receipt(receipt,data)['saved']
        assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
        assert 'secret' not in receipt.read_text()
        try:
            save_repair_receipt(receipt,data)
        except FileExistsError:
            pass
        else:
            raise AssertionError('receipt overwritten')


def test_rollback_from_private_receipt():
    from kirabridge.doctor_repair import save_repair_receipt, rollback_from_receipt
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'launcher'
        receipt = Path(directory) / 'receipt.json'
        path.write_text('test')
        path.chmod(0o600)
        result = repair_launcher_permissions(path, approve=True)
        save_repair_receipt(receipt, result)
        assert rollback_from_receipt(path, receipt)['status'] == 'approval_required'
        assert rollback_from_receipt(path, receipt, approve=True)['status'] == 'rolled_back'
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_receipt_rejects_replaced_target_and_wrong_path():
    from kirabridge.doctor_repair import save_repair_receipt, rollback_from_receipt
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'launcher'
        receipt = Path(directory) / 'receipt.json'
        path.write_text('original')
        path.chmod(0o600)
        save_repair_receipt(receipt, repair_launcher_permissions(path, approve=True))
        other = Path(directory) / 'other'
        other.write_text('original')
        other.chmod(0o700)
        assert rollback_from_receipt(other, receipt, approve=True)['status'] == 'target_mismatch'
        path.unlink()
        path.write_text('original')
        path.chmod(0o700)
        assert rollback_from_receipt(path, receipt, approve=True)['status'] == 'target_mismatch'


def test_receipt_rejects_modified_target_contents():
    from kirabridge.doctor_repair import save_repair_receipt, rollback_from_receipt
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'launcher'
        receipt = Path(directory) / 'receipt.json'
        path.write_text('original')
        path.chmod(0o600)
        save_repair_receipt(receipt, repair_launcher_permissions(path, approve=True))
        path.write_text('changed!')
        assert rollback_from_receipt(path, receipt, approve=True)['status'] == 'target_mismatch'


def test_tampered_receipt_is_rejected():
    import json
    from kirabridge.doctor_repair import save_repair_receipt, rollback_from_receipt
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'launcher'
        receipt = Path(directory) / 'receipt.json'
        path.write_text('test')
        path.chmod(0o600)
        save_repair_receipt(receipt, repair_launcher_permissions(path, approve=True))
        record = json.loads(receipt.read_text())
        record['before_mode'] = '0o777'
        receipt.write_text(json.dumps(record))
        assert rollback_from_receipt(path, receipt, approve=True)['status'] == 'integrity_failed'
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_missing_receipt_key_blocks_rollback():
    from kirabridge.doctor_repair import save_repair_receipt, rollback_from_receipt
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'launcher'
        receipt = Path(directory) / 'receipt.json'
        path.write_text('test')
        path.chmod(0o600)
        save_repair_receipt(receipt, repair_launcher_permissions(path, approve=True))
        receipt.with_name(receipt.name + '.key').unlink()
        assert rollback_from_receipt(path, receipt, approve=True)['status'] == 'integrity_unavailable'


def test_world_accessible_receipt_directory_rejected():
    from kirabridge.doctor_repair import save_repair_receipt
    with TemporaryDirectory() as directory:
        folder = Path(directory) / 'open'
        folder.mkdir(mode=0o755)
        folder.chmod(0o755)  # override process umask for this negative test
        try:
            save_repair_receipt(folder / 'receipt.json', {'status':'repaired','changed':True})
        except ValueError:
            pass
        else:
            raise AssertionError('insecure receipt directory accepted')


def test_insecure_key_permissions_block_rollback():
    from kirabridge.doctor_repair import save_repair_receipt, rollback_from_receipt
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'launcher'
        receipt = Path(directory) / 'receipt.json'
        path.write_text('test')
        path.chmod(0o600)
        save_repair_receipt(receipt, repair_launcher_permissions(path, approve=True))
        receipt.with_name(receipt.name + '.key').chmod(0o644)
        assert rollback_from_receipt(path, receipt, approve=True)['status'] == 'integrity_unavailable'
