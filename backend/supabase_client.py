"""
supabase_client — thin wrapper around supabase-py for what this backend
needs: pulling the raw file down from Storage, keeping the `jobs` row
updated as processing happens, and reading/writing prospects + claims.

Uses the SERVICE ROLE key deliberately — this code runs server-side only
and needs to bypass row-level security. Never expose
SUPABASE_SERVICE_ROLE_KEY to any frontend code.
"""

from __future__ import annotations

from pathlib import Path

from supabase import Client, create_client

from config import SUPABASE

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


def get_org_prospect_candidates(org_id: str) -> list[dict]:
    client = get_client()
    res = client.table("prospects").select("id, name, company, email").eq("org_id", org_id).execute()
    return res.data or []


def upsert_prospect(org_id: str, prospect_id: str | None, fields: dict) -> str:
    """Updates the existing prospect if prospect_id is given, otherwise
    creates a new one. Returns the prospect's id either way."""
    client = get_client()
    if prospect_id:
        client.table("prospects").update(fields).eq("id", prospect_id).execute()
        return prospect_id
    res = client.table("prospects").insert({**fields, "org_id": org_id}).execute()
    return res.data[0]["id"]


def insert_claims(rows: list[dict]) -> list[dict]:
    """Returns the inserted rows WITH their real database ids — verify()
    needs those ids to write results back to the right claim."""
    if not rows:
        return []
    client = get_client()
    res = client.table("claims").insert(rows).execute()
    return res.data or []


def update_claim(claim_id: str, **fields) -> None:
    client = get_client()
    client.table("claims").update(fields).eq("id", claim_id).execute()


def get_claims_for_job(job_id: str) -> list[dict]:
    """Fetch claims AFTER verify has updated them — main.py's in-memory
    list from insert_claims() goes stale the moment verify writes back,
    so this re-fetches the authoritative current state."""
    client = get_client()
    res = client.table("claims").select("*").eq("job_id", job_id).execute()
    return res.data or []


def get_open_claims_for_prospect(prospect_id: str, exclude_job_id: str) -> list[dict]:
    client = get_client()
    res = (
        client.table("claims")
        .select("*")
        .eq("prospect_id", prospect_id)
        .eq("state", "open")
        .neq("job_id", exclude_job_id)
        .execute()
    )
    return res.data or []


def get_job(job_id: str) -> dict | None:
    client = get_client()
    res = client.table("jobs").select("*").eq("id", job_id).single().execute()
    return res.data
