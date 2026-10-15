import hashlib


def generate_finding_id(
    *,
    file: str,
    category: str,
    severity: str,
    title: str,
) -> str:
    payload = "|".join(
        [
            file.strip().lower(),
            category.strip().lower(),
            severity.strip().lower(),
            title.strip().lower(),
        ]
    )

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()