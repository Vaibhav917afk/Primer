"""
prospect_matching — decides whether the identified PROSPECT participant
belongs to an existing prospect record (someone we've already talked to,
possibly across several past calls — the actual "nothing connects call 1
to call 5" problem this project exists to solve) or is a new person.

Kept as a pure function, separate from the Supabase call that fetches the
candidate list, so the matching logic itself is fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from extract import Participant


@dataclass
class ProspectCandidate:
    id: str
    name: str | None
    company: str | None
    email: str | None


def find_matching_prospect(persona: Participant, candidates: list[ProspectCandidate]) -> str | None:
    """Returns the matching prospect's id, or None if this looks like a
    new person. Matching priority: exact email (most reliable identifier)
    first, then name+company together (a name alone is too ambiguous —
    two different prospects can share a first name)."""
    if persona.email:
        email_lower = persona.email.strip().lower()
        for c in candidates:
            if c.email and c.email.strip().lower() == email_lower:
                return c.id

    if persona.name and persona.company:
        name_lower = persona.name.strip().lower()
        company_lower = persona.company.strip().lower()
        for c in candidates:
            if (
                c.name and c.name.strip().lower() == name_lower
                and c.company and c.company.strip().lower() == company_lower
            ):
                return c.id

    return None
