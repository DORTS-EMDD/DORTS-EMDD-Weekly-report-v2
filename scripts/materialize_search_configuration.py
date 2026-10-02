"""Validate and materialize the single declarative Search configuration.

This is authoring/governance tooling. Runtime modules consume the JSON asset via
RegionRegistry and never parse the Markdown governance documents.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.weekly_report.contracts import SearchProviderId  # noqa: E402
from src.weekly_report.region_registry import CONFIGURATION_PATH, RegionRegistry  # noqa: E402


_TOP_LEVEL_FIELDS = frozenset(
    {
        "configuration_version",
        "region_modes",
        "selected_markets",
        "global_targets",
        "global_markets",
        "profiles",
        "discovery_intents",
        "query_families",
        "planning_limits",
    }
)

_ARCHITECTURE_CONTRACT = ROOT / "docs" / "ARCHITECTURE_CONTRACT.md"
_LANGUAGE_PROFILE_CONTRACT = ROOT / "docs" / "SEARCH_LANGUAGE_PROFILES.md"


def _load(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, Mapping):
        raise ValueError("Search configuration must be a JSON object")
    unknown = set(value) - _TOP_LEVEL_FIELDS
    if unknown:
        raise ValueError(f"unsupported configuration fields: {sorted(unknown)}")
    return value


def validate_configuration(path: str | Path = CONFIGURATION_PATH) -> RegionRegistry:
    """Validate every field through the typed owner and its lossless round trip."""

    source = _load(Path(path))
    registry = RegionRegistry.from_mapping(source)
    _validate_governance_documents(registry)
    _validate_provider_targets(registry)
    materialized = registry.as_mapping()
    round_trip = RegionRegistry.from_mapping(materialized).as_mapping()
    if materialized != round_trip:
        raise ValueError("typed configuration materialization is not deterministic")
    return registry


def _extract_governed_vocabulary(language: str) -> dict[str, dict[str, dict[str, tuple[str, ...]]]]:
    """Extract only the explicit profile vocabulary table in §5."""

    section = language.split("## 5. Intent vocabulary groups", 1)[-1]
    section = section.split("## 6. Intent and profile rules", 1)[0]
    profiles: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {}
    current_profile: str | None = None
    for line in section.splitlines():
        heading = re.match(r"^### `([^`]+)` —", line)
        if heading:
            current_profile = heading.group(1)
            profiles[current_profile] = {}
            continue
        if current_profile is None:
            continue
        entry = re.match(r"^\* `([^`]+)`: (.+)$", line)
        if not entry:
            continue
        intent, body = entry.groups()
        groups: dict[str, tuple[str, ...]] = {}
        for segment in body.split(";"):
            segment = segment.strip().rstrip(".").strip().strip("`")
            if "=" not in segment:
                continue
            group_name, raw_terms = segment.split("=", 1)
            group_name = group_name.strip()
            terms = tuple(term.strip() for term in raw_terms.split(","))
            if not terms or any(not term for term in terms):
                raise ValueError(f"empty governed vocabulary term in {current_profile}/{intent}")
            groups[group_name] = terms
        if not groups:
            raise ValueError(f"missing governed vocabulary groups in {current_profile}/{intent}")
        profiles[current_profile][intent] = groups
    if not profiles or any(set(intents) != {"technology", "major_incident", "operations", "procurement"} for intents in profiles.values()):
        raise ValueError("governance vocabulary must expose all four intents for every profile")
    return profiles


def _source_with_governed_vocabulary(source: Mapping[str, Any], language: str) -> dict[str, Any]:
    vocabulary = _extract_governed_vocabulary(language)
    profiles = []
    for profile in source.get("profiles", ()):
        profile = dict(profile)
        profile_id = profile.get("profile_id")
        if profile_id not in vocabulary:
            raise ValueError(f"runtime profile is not governed: {profile_id}")
        profile["intent_vocabulary"] = vocabulary[profile_id]
        profiles.append(profile)
    materialized = dict(source)
    materialized["profiles"] = profiles
    return materialized


def _profile_cell(value: str) -> tuple[str, ...]:
    value = value.strip()
    if value in {"", "—", "-"}:
        return ()
    return tuple(part.strip().strip("`") for part in value.split(","))


def _validate_governance_documents(registry: RegionRegistry) -> None:
    """Check the small governed tables/markers without scraping whole Markdown."""

    architecture = _ARCHITECTURE_CONTRACT.read_text(encoding="utf-8")
    language = _LANGUAGE_PROFILE_CONTRACT.read_text(encoding="utf-8")
    for marker in (
        "目前 selected mode 包含上述 19 個市場",
        r"GLOBAL_MODE_TAIWAN_BEHAVIOR\s*=\s*EXCLUDE_DISCOVERY",
        r"TAIWAN_SELECTED_SEARCH_PLAN_ITEMS\s*=\s*FORBIDDEN",
        r"TAIWAN_GLOBAL_SEARCH_PLAN_ITEMS\s*=\s*FORBIDDEN",
        r"PROVIDER_TARGET_CANONICAL_ID\s*=\s*google_news_rss",
        r"DEFAULT_PROVIDER_TARGET\s*=\s*FORBIDDEN",
        r"MAX_PROVIDER_INVOCATIONS_PER_PLAN_ITEM\s*=\s*1",
        r"HIDDEN_TRANSPORT_RETRY\s*=\s*FORBIDDEN",
        r"REDIRECT_FOLLOW_COUNT\s*=\s*0",
        r"PAGINATION\s*=\s*ONE_PROVIDER_REQUEST_PAGE_ONLY",
        r"EXECUTION_CONCURRENCY\s*=\s*SEQUENTIAL",
    ):
        if re.search(marker, architecture) is None:
            raise ValueError(f"Architecture Contract marker missing: {marker}")
    for marker in (
        "The 13 selected-market profiles are therefore:",
        "It is not failure-triggered fallback, retry, alternate-provider rescue",
        "The profile list and mapping were recovered from repository evidence",
        "It **MUST** enforce a configured query budget",
        "Query families are bounded discovery composition templates governed by",
    ):
        if marker not in language:
            raise ValueError(f"Search language contract marker missing: {marker}")

    profile_block = re.search(
        r"The 13 selected-market profiles are therefore:\s*```text\s*([^\n]+)", language
    )
    if profile_block is None:
        raise ValueError("selected profile ID block is missing")
    governed_profile_ids = tuple(profile_block.group(1).split(", "))
    if registry.selected_profile_ids != governed_profile_ids:
        raise ValueError("runtime selected profiles do not match governance content")

    intent_block = language.split("The four discovery intents use one canonical machine-ID mapping:", 1)[-1]
    intent_block = intent_block.split("`major_incident` is", 1)[0]
    governed_intents = tuple(re.findall(r"(?m)^([a-z_]+)\s+->\s+(.+)$", intent_block))
    runtime_intents = tuple(
        (intent["id"], intent["display_label"])
        for intent in registry.as_mapping()["discovery_intents"]
    )
    if governed_intents != runtime_intents:
        raise ValueError("runtime discovery intent mapping does not match governance content")

    section = language.split("## 3. Selected markets and deterministic mapping", 1)[-1]
    section = section.split("## 4. Query composition and bounds", 1)[0]
    rows: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {}
    for line in section.splitlines():
        if not line.startswith("| ") or line.count("|") < 4:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in {"Selected market", "---"}:
            continue
        if set(cells[0]) <= {"-"}:
            continue
        rows[cells[0]] = (_profile_cell(cells[1]), _profile_cell(cells[2]), _profile_cell(cells[3]))
    expected = {
        market.display_name: (
            market.primary_profiles,
            market.secondary_profiles,
            market.english_supplement_profiles,
        )
        for market in registry.selected_markets
    }
    if rows != expected:
        raise ValueError("selected-market language table does not match runtime fields")

    governed_vocabulary = _extract_governed_vocabulary(language)
    runtime_vocabulary = {
        profile.profile_id: {
            intent: {group: tuple(terms) for group, terms in groups.items()}
            for intent, groups in profile.intent_vocabulary.items()
        }
        for profile in registry.profiles
    }
    if runtime_vocabulary != governed_vocabulary:
        raise ValueError("runtime profile vocabulary does not match governance content")


def _validate_provider_targets(registry: RegionRegistry) -> None:
    """Keep executable provider routing inside the typed governed vocabulary."""

    canonical_ids = {provider.value for provider in SearchProviderId}
    for family in registry.query_families:
        provider_target = getattr(family.provider_target, "value", family.provider_target)
        if provider_target not in canonical_ids:
            raise ValueError(f"query family provider target is not governed: {provider_target}")
        if provider_target == "default":
            raise ValueError("default provider target is forbidden")


def materialize_configuration(
    source_path: str | Path = CONFIGURATION_PATH,
    destination_path: str | Path | None = None,
) -> RegionRegistry:
    source = _load(Path(source_path))
    language = _LANGUAGE_PROFILE_CONTRACT.read_text(encoding="utf-8")
    hydrated = _source_with_governed_vocabulary(source, language)
    registry = RegionRegistry.from_mapping(hydrated)
    _validate_governance_documents(registry)
    _validate_provider_targets(registry)
    materialized = registry.as_mapping()
    if materialized != RegionRegistry.from_mapping(materialized).as_mapping():
        raise ValueError("typed configuration materialization is not deterministic")
    destination = Path(destination_path or source_path)
    destination.write_text(
        json.dumps(registry.as_mapping(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=CONFIGURATION_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true", help="validate without writing (the default)")
    parser.add_argument("--write", action="store_true", help="write the canonical materialized asset")
    args = parser.parse_args()
    registry = materialize_configuration(args.source, args.output) if args.write else validate_configuration(args.source)
    print(f"SEARCH_CONFIGURATION_VALID = YES")
    print(f"CONFIGURATION_VERSION = {registry.configuration_version}")
    print(f"SELECTED_MARKET_COUNT = {registry.selected_market_count}")
    print(f"GLOBAL_CONFIGURED_TARGET_COUNT = {registry.global_target_count}")
    print(f"SELECTED_PROFILE_COUNT = {len(registry.selected_profile_ids)}")
    print("MATERIALIZATION_DETERMINISTIC = YES")
    print("FIELD_CONTENT_PARITY_VALIDATION = YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
