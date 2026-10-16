"""Tag naming schemes and version ordering.

A tag scheme is a pattern such as ``v{version}``, ``{version}`` or ``my-pkg@{version}``
(monorepos). ``auto`` accepts an optional ``v`` prefix followed by a dotted numeric version,
which covers semver, PEP 440 and calver tags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

_VERSION_RE = r"(?P<version>\d+(?:\.\d+)*(?:[-.+_]?[0-9A-Za-z][0-9A-Za-z.+_-]*)?)"


@dataclass(frozen=True)
class TagScheme:
    pattern: str = "auto"

    @property
    def regex(self) -> re.Pattern[str]:
        if self.pattern == "auto":
            return re.compile(rf"^v?{_VERSION_RE}$")
        if "{version}" not in self.pattern:
            raise ValueError(f"Tag pattern {self.pattern!r} must contain '{{version}}'")
        before, after = self.pattern.split("{version}", 1)
        return re.compile(rf"^{re.escape(before)}{_VERSION_RE}{re.escape(after)}$")

    def version_of(self, tag: str) -> str | None:
        match = self.regex.match(tag)
        return match.group("version") if match else None

    def format(self, version: str) -> str:
        if self.pattern == "auto":
            return version if version.startswith("v") else f"v{version}"
        return self.pattern.replace("{version}", version)


def from_commitizen(tag_format: str) -> TagScheme | None:
    """Translate a commitizen ``tag_format`` (``v$version``, ``${version}``) into a scheme."""
    pattern = re.sub(r"\$\{?version\}?", "{version}", tag_format)
    if "{version}" not in pattern or "$" in pattern:
        return None  # $major/$minor style formats: rely on auto detection instead
    return TagScheme(pattern)


def parse_version(text: str | None) -> Version | None:
    if not text:
        return None
    try:
        return Version(text)
    except InvalidVersion:
        # semver build metadata/prerelease spellings packaging refuses, e.g. 1.0.0-beta.x
        try:
            return Version(re.sub(r"[-_.](?=[A-Za-z])", "", text.split("+")[0]))
        except InvalidVersion:
            return None


def is_prerelease(text: str | None) -> bool:
    version = parse_version(text)
    return bool(version and (version.is_prerelease or version.is_devrelease))
