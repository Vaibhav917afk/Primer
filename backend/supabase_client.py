"""
supabase_client — thin wrapper around supabase-py for the two things this
backend needs: pulling the raw file down from Storage, and keeping the
`jobs` row updated as processing happens.

Uses the SERVICE ROLE key deliberately — this code runs server-side only
and needs to bypass row-level security to update any job, not just ones a
particular end user owns. Never expose SUPABASE_SERVICE_ROLE_KEY to any
frontend code.
"""

from __future__ import annotations

from pathlib import Path

from supabase import Client, create_client

from .config import SUPABASE

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE.url or not SUPABASE.service_role_key:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — check .env"
            )
        _client = create_client(SUPABASE.url, SUPABASE.service_role_key)
    return _client


def download_raw_file(storage_path: str, local_dir: Path) -> Path:
    """Pull the uploaded file down from the raw-uploads bucket to a local
    temp path, so ingest.py (unchanged) can work on it exactly as before."""
    client = get_client()
    data = client.storage.from_(SUPABASE.raw_bucket).download(storage_path)
    local_path = local_dir / Path(storage_path).name
    local_path.write_bytes(data)
    return local_path


def upload_output_file(local_path: Path, storage_path: str) -> None:
    client = get_client()
    with open(local_path, "rb") as f:
        client.storage.from_(SUPABASE.output_bucket).upload(
            storage_path, f.read(), {"upsert": "true"}
        )


def update_job(job_id: str, **fields) -> None:
    client = get_client()
    client.table("jobs").update(fields).eq("id", job_id).execute()


def get_job(job_id: str) -> dict | None:
    client = get_client()
    res = client.table("jobs").select("*").eq("id", job_id).single().execute()
    return res.data
