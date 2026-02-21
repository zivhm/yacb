"""Security utilities: path traversal protection, command filtering."""

from pathlib import Path


def resolve_safe_path(path: str, allowed_dir: Path | None = None) -> Path:
    """Resolve path and optionally enforce directory restriction."""
    resolved = Path(path).expanduser().resolve()
    if allowed_dir:
        allowed = allowed_dir.resolve()
        try:
            resolved.relative_to(allowed)
        except ValueError as e:
            raise PermissionError(
                f"Path {path} is outside allowed directory {allowed_dir}"
            ) from e
    return resolved
