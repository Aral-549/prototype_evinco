"""Forensic chain of custody for an analysis run.

MarSlick produces material intended to support enforcement action by a coastal
authority. Any such output has to answer three questions before its conclusions
are worth anything:

  1. What exactly was analysed?          -> digest of the image bytes
  2. What exactly analysed it?           -> digest of the model weights + code version
  3. Can anyone else get the same answer? -> every parameter and the RNG seed

A number on a map that cannot be reproduced is an allegation, not evidence. The
manifest records all three and seals them with a digest over their canonical
JSON, so that an altered dossier fails verification.

Scope limit, stated plainly: these are integrity digests, not signatures. They
prove a submitted manifest is internally consistent with the data it names; they
do not prove who produced it. Non-repudiation needs the manifest signed with an
authority-held key, which is the natural production next step and is deliberately
out of scope here.
"""
import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

logger = logging.getLogger('pipeline')

MANIFEST_VERSION = '1.0.0'
_CHUNK = 1024 * 1024  # stream in 1 MiB blocks; SAR scenes can exceed RAM


def sha256_file(path: str) -> str:
    """Streaming SHA-256 of a file. Returns 'unavailable' if it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            while True:
                block = f.read(_CHUNK)
                if not block:
                    break
                h.update(block)
        return h.hexdigest()
    except Exception as exc:
        logger.warning(f'Could not digest file {path}: {exc}')
        return 'unavailable'


def sha256_path(path: str) -> str:
    """Digest of a file, or of a directory's full sorted contents.

    Checkpoints ship either as a single file or as a PyTorch directory-format
    bundle, so both must produce a stable digest. Directory entries are sorted by
    relative path so the result does not depend on filesystem iteration order.
    """
    if not path or not os.path.exists(path):
        return 'unavailable'
    if os.path.isfile(path):
        return sha256_file(path)

    h = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, path)
            h.update(rel.encode('utf-8'))
            h.update(sha256_file(full).encode('ascii'))
    return h.hexdigest()


def canonical_json(obj) -> str:
    """Deterministic JSON: sorted keys, fixed separators, UTF-8 preserved.

    Key order, whitespace and float repr must not vary between runs or machines,
    or two identical analyses would produce different digests.
    """
    return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, default=_json_default)


def _json_default(o):
    if isinstance(o, datetime):
        return o.astimezone(timezone.utc).isoformat()
    if hasattr(o, 'tolist'):
        return o.tolist()
    if hasattr(o, 'item'):
        return o.item()
    return str(o)


def _normalise(obj):
    """Coerce values so representation differences do not change the digest.

    `1` and `1.0` are the same parameter; numpy scalars and Python scalars are
    the same value. Without this, swapping an int literal for a float in a
    settings file would silently invalidate every previously issued manifest.
    """
    if isinstance(obj, dict):
        return {str(k): _normalise(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_normalise(v) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        f = float(obj)
        # repr via a fixed format so 1 and 1.0 and 1.00 all canonicalise alike
        return f'{f:.12g}'
    if isinstance(obj, datetime):
        return obj.astimezone(timezone.utc).isoformat()
    if obj is None or isinstance(obj, str):
        return obj
    if hasattr(obj, 'item'):
        return _normalise(obj.item())
    return str(obj)


def git_commit() -> str:
    """Current commit of the analysing code, or 'unavailable' outside a repo."""
    try:
        out = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            commit = out.stdout.strip()
            dirty = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True, text=True, timeout=5,
            )
            if dirty.returncode == 0 and dirty.stdout.strip():
                return f'{commit}-dirty'
            return commit
    except Exception as exc:
        logger.debug(f'git commit unavailable: {exc}')
    return 'unavailable'


@dataclass
class EvidenceManifest:
    manifest_version: str
    input_sha256: str
    input_filename: str
    input_bytes: int
    model_sha256: str
    model_name: str
    model_version: str
    model_checkpoint_id: str
    code_version: str
    parameters: dict
    metocean_provenance: list
    stage_digests: dict
    created_at: str
    content_sha256: str = ''
    manifest_sha256: str = ''

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False,
                          default=_json_default)


def _content_payload(m: dict) -> dict:
    """The fields that describe WHAT was analysed, excluding when the manifest was made.

    `created_at` is inside `manifest_sha256` (so re-issuing a manifest is visible)
    but outside `content_sha256` (so two runs of the same analysis on different
    days can still be shown to be the same analysis).
    """
    return {k: v for k, v in m.items()
            if k not in ('created_at', 'content_sha256', 'manifest_sha256')}


def build_manifest(image_path: str, model_info: dict = None, checkpoint_path: str = None,
                   parameters: dict = None, metocean_records: list = None,
                   stage_digests: dict = None) -> EvidenceManifest:
    """Assemble and seal the chain-of-custody record for one analysis run."""
    model_info = model_info or {}
    parameters = parameters or {}
    metocean_records = metocean_records or []
    stage_digests = stage_digests or {}

    try:
        size = os.path.getsize(image_path)
    except Exception:
        size = -1

    fields = {
        'manifest_version': MANIFEST_VERSION,
        'input_sha256': sha256_file(image_path),
        'input_filename': os.path.basename(image_path or ''),
        'input_bytes': size,
        'model_sha256': sha256_path(checkpoint_path),
        'model_name': str(model_info.get('name', 'unknown')),
        'model_version': str(model_info.get('version', 'unknown')),
        'model_checkpoint_id': str(model_info.get('checkpoint_id', 'unknown')),
        'code_version': git_commit(),
        'parameters': _normalise(parameters),
        'metocean_provenance': _normalise(metocean_records),
        'stage_digests': _normalise(stage_digests),
    }

    content_sha = hashlib.sha256(canonical_json(fields).encode('utf-8')).hexdigest()
    fields['created_at'] = datetime.now(timezone.utc).isoformat()
    fields['content_sha256'] = content_sha

    manifest_sha = hashlib.sha256(
        canonical_json(_normalise(fields)).encode('utf-8')).hexdigest()

    return EvidenceManifest(**fields, manifest_sha256=manifest_sha)


def digest_stage_output(payload) -> str:
    """Digest of one pipeline stage's output, for the per-stage integrity record."""
    return hashlib.sha256(canonical_json(_normalise(payload)).encode('utf-8')).hexdigest()


def verify(manifest, image_path: str = None, checkpoint_path: str = None) -> tuple:
    """Check a manifest's internal seal and, optionally, the artefacts it names.

    Returns (ok, reasons). `reasons` names each specific mismatch so a reviewer
    can act on it rather than being told only that something is wrong.
    """
    m = manifest.to_dict() if isinstance(manifest, EvidenceManifest) else dict(manifest)
    reasons = []

    recomputed = hashlib.sha256(
        canonical_json(_normalise(
            {k: v for k, v in m.items() if k != 'manifest_sha256'}
        )).encode('utf-8')).hexdigest()
    if recomputed != m.get('manifest_sha256'):
        reasons.append(
            f"manifest_sha256 mismatch: the manifest's own fields hash to {recomputed} "
            f"but it carries {m.get('manifest_sha256')}. The record has been altered "
            f"since it was issued."
        )

    content_recomputed = hashlib.sha256(
        canonical_json(_content_payload(m)).encode('utf-8')).hexdigest()
    if content_recomputed != m.get('content_sha256'):
        reasons.append(
            f'content_sha256 mismatch: expected {m.get("content_sha256")}, '
            f'recomputed {content_recomputed}.'
        )

    if image_path is not None:
        actual = sha256_file(image_path)
        if actual != m.get('input_sha256'):
            reasons.append(
                f'Input image mismatch: {os.path.basename(image_path)} hashes to {actual}, '
                f'but this manifest attests to {m.get("input_sha256")}. This is not the '
                f'image that was analysed.'
            )

    if checkpoint_path is not None:
        actual = sha256_path(checkpoint_path)
        if actual != m.get('model_sha256'):
            reasons.append(
                f'Model checkpoint mismatch: {checkpoint_path} hashes to {actual}, '
                f'but this manifest attests to {m.get("model_sha256")}. A different model '
                f'produced the result being verified.'
            )

    return (len(reasons) == 0, reasons)
