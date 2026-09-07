# src/services/payment_proof_service.py
"""
Shared proof-of-payment file handling for Installation Recovery and AMC
Recovery payment recording - the one piece of new code both desks call
into (see the recovery-ops spec's Payment Recording section).
"""
import os
import uuid
from typing import Optional

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def _resolve_upload_folder() -> str:
    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    if not os.path.isabs(upload_folder):
        project_root = os.path.abspath(os.path.join(current_app.root_path, '..'))
        upload_folder = os.path.abspath(os.path.join(project_root, upload_folder))
    return upload_folder


def save_payment_proof(file_storage: Optional[FileStorage], subfolder: str, entity_id) -> Optional[str]:
    """Validate and save a proof-of-payment image (JPG/PNG, under 5MB),
    returning its path relative to UPLOAD_FOLDER, or None if no file was
    provided. Raises ValueError on an invalid file - the caller turns that
    into a flashed message or a JSON error, whichever fits its route."""
    if not file_storage or not file_storage.filename:
        return None

    ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError('Proof of payment must be a JPG or PNG image.')

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_FILE_SIZE:
        raise ValueError('Proof of payment must be under 5 MB.')
    if size == 0:
        raise ValueError('Proof of payment file is empty.')

    target_dir = os.path.join(_resolve_upload_folder(), 'payment_proofs', subfolder)
    os.makedirs(target_dir, exist_ok=True)

    filename = secure_filename(f"{entity_id}_{uuid.uuid4().hex[:8]}.{ext}")
    filepath = os.path.join(target_dir, filename)
    file_storage.save(filepath)

    return os.path.join('payment_proofs', subfolder, filename)


def resolve_proof_path(relative_path: str) -> str:
    """Absolute filesystem path for a stored proof, for use with send_from_directory."""
    return os.path.join(_resolve_upload_folder(), relative_path)
