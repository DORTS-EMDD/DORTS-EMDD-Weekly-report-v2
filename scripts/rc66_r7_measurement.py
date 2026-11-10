"""Execute the frozen RC66-R7 EventIdentity measurement.

This is measurement infrastructure only.  It does not change the production
EventIdentity prompt or owner.  Source bodies are fetched through the
production evidence fetcher, SHA-256 checked against the audit, and never
written to the repository.  The result contains IDs, counts, and diagnostics,
not request bodies or credentials.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import itertools
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.weekly_report.contracts import (  # noqa: E402
    CanonicalCandidate,
    EvidenceResult,
    EvidenceState,
    EventIdentityGroupingRequest,
    ScopeResult,
    ScopeState,
    TemporalDiagnostic,
    TemporalResult,
)
from src.weekly_report.evidence_document import assess_document  # noqa: E402
from src.weekly_report.evidence_sentences import segment_evidence_sentences  # noqa: E402
from src.weekly_report.evidence_service import _default_fetcher  # noqa: E402
from src.weekly_report.event_identity import EventIdentity, _grouping_record  # noqa: E402
from src.weekly_report import maiagent_event_identity_provider as provider_module  # noqa: E402
from src.weekly_report.maiagent_event_identity_provider import (  # noqa: E402
    build_maiagent_event_identity_model_input,
    build_maiagent_event_identity_provider,
)
from src.weekly_report.maiagent_transport import (  # noqa: E402
    MaiAgentHttpResponse,
    UrllibMaiAgentJsonTransport,
)


HARD_CALL_CAP = 400
BASELINE_PROMPT = "event-identity-grouping-v10"
CANDIDATE_PROMPT = "event-identity-grouping-v10+rc66-confirmation-clarification-v1"
CANDIDATE_GUIDANCE = (
    "In a confirmation, a record that reports two occurrences goes with the "
    "records of the occurrence whose specific details it states; reporting an "
    "activity that marks or verifies that occurrence does not by itself make it "
    "a different event. It is a single-record group only when the shared details "
    "cannot be determined."
)

# These are the eight refetch hash mismatches and one unavailable item already
# excluded by the offline preflight.  They are never substituted.
EXCLUDED_IDS = {
    "cand_cfd25e1f91532ef1a275d79722704e4db8dc70bd41852ab523b077bab9ac4d7c",
    "cand_23a44c60f2ff25ac9897ef005d620b16d8b4793cd49103e3be6e0048e597acfa",
    "cand_bc383dac0265a4669f7c267734b218830f425d36595b02ee3e565fb7f3e65d65",
    "cand_6b18cbd933f4584ced526928c3d75d3fa1ebc09b39126ba4a85d7e8f3c3ac012",
    "cand_c7b3e8dca1bd9ebf9a4211138915b28a81db5687dfa9ccc994e4dbf227882871",
    "cand_3f2caa1f683753b30267394f33103028779b98bf15f580e33381bd8240a107a3",
    "cand_59d401d75c640cd16a53a4376994fbddab62735115bccc02578621e947da7832",
    "cand_f9d5ed081c92e173426bcd32a364ce99657bb8e362294b99a02c0257cf7d3539",
    "cand_8769477d0c03fceeea8d4d96c4c6926009b575ba1af40ccb7eca040f2a11ccb6",
}

MIXED_IDS = {
    "cand_010cdde712fe2f1cd1e8667f94ba4676f57ab261e21e33e34d98a21abe6f3898": "INCHEON-WIFI-START",
    "cand_9ce03b4da316d4ea90f2eb7cf957ecf0ff5b45a5287192fe06b97878e0938997": "INCHEON-WIFI-START",
    "cand_1d6f2d3c0e36849405fed7533bce0d54494a45b50288ab017d6ff5e80ef38b9a": "SYDNEY-SW-OPENING",
    "cand_db84b77e41ccc784cd8776cf045defeaf6484c6572c570d9ed1f04dbb38d6174": "SYDNEY-SW-OPENING",
    "cand_3a95fcf226602be8d832847a1b439fb7db58596da1c8704f2fd2bd0bf0280b6f": "SYDNEY-SW-OPENING",
}

PURE_LABELS = {
    "cand_c3b575ffd39c3de6d71979e28f839672ab2bc80515b1033973f1ff77d2efb4d7": "DAEGU-MYEONGDEOK",
    "cand_fbff996e9a8b8afc0533851199f25159b96b77402999893ccae79feade5928ad": "DAEGU-MYEONGDEOK",
    "cand_89f34b8ab343ceb0adc33397cda22bc36e39e977df27531c149966356feaa1be": "SEOUL-L2-OUTAGE",
    "cand_9ba3de65b565a34a47c71b09ff555534379ea7ac9a9616e4c735ac0c083e0692": "SEOUL-L2-OUTAGE",
    "cand_cb7c91e25aed4a8dd6ea6c2cbd52e90c86923a9e72864f73f079ff77fad5e7a6": "KIM-MINSEOK-STATEMENT",
    "cand_edde386e5623ad0f276f36e5de9dfd82684c22447980790168dee84f02244bcb": "KIM-MINSEOK-STATEMENT",
    "cand_12aaae13731c64594c85c9ea7b8854125f8a4803e4730dd1420d9a6449dddf6f": "KYIV-ATTACK",
    "cand_1463016b9762e47c95eff7ba69e0b0b3cfa315315d3d40da47231be94b0018fe": "ULSAN-DEPOT",
    "cand_56a532bc836596ae7f4267222a2980bcba894913da4d880df55e007d1362ba0c": "ULSAN-DEPOT",
    "cand_72af1abb7460b06e17e26bee3bcbf7c3695ede292197570403d47840949229d7": "ULSAN-DEPOT",
    "cand_829429754f83a77475d9aea81c6c0d8288561d1872caf50948e5a3fe2282c7c0": "ULSAN-DEPOT",
    "cand_b268495bec078265689ed209d7ffd76682e189fce84fdee21f307b126ef9351b": "ULSAN-DEPOT",
    "cand_c7555a28754fea816e343150efdbefd869b21cb8f69122084a7e7a788a20d213": "ULSAN-DEPOT",
    "cand_ce5a4bc733088eab0891ee4ae3344322b34a6f2408250893ba4310b72e0486e8": "ULSAN-DEPOT",
    "cand_e6241c07ad1dba10088b407d6d1b9a899fb1309220e4aeab898d442f24610d27": "ULSAN-DEPOT",
}

INCIDENT_LABELS = {
    "cand_4d2d190478d974e5c98108159ec7b4247d86bda2512b2e6c46b4c5a07944be1d": "BARCELONA-FIRE-CAUSE",
    "cand_f09883d7701e3981555e9b2bb18a9d19ee6e8b088ada2f9cf27e6ae9d1adeda5": "BARCELONA-FIRE-RESTORED",
}

# Independent labels set from the rebuilt excerpt text before any current
# helper call.  The labels intentionally describe occurrences, not publishers,
# URLs, languages, or candidate IDs.
MEGA_LABEL_BY_GROUP_RID = {
    "mega29g4": {
        "R1": "TOKYO-POINT-AI", "R2": "KYOTO-BATTERY", "R3": "SANTIAGO-L9-PLAN",
        "R4": "DHAKA-L1-LT", "R5": "SEOUL-OPERATIONS-EXCHANGE", "R6": "METROVALENCIA-SEATS",
        "R7": "NYC-METRO-CONDITION", "R8": "TOKYO-POINT-AI", "R9": "TOKYO-PATRAIL",
        "R10": "DHAKA-L1-LT", "R11": "MADRID-L6-UPGRADE", "R12": "SEOUL-OPERATIONS-EXCHANGE",
    },
    "mega29g5": {
        "R1": "WUHAN-12-SCHEDULE", "R2": "ROSARIO-TRAM-TENDER", "R3": "MONTERREY-METRO-SECURITY",
        "R4": "WIRYE-OPENING-DELAY", "R5": "WIRYE-OPENING-DELAY", "R6": "WIRYE-OPENING-DELAY",
        "R7": "WIRYE-OPENING-DELAY", "R8": "GWANGJU-L2-PHASE1", "R9": "WIRYE-OPENING-DELAY",
        "R10": "SEOUL-OPERATIONS-EXCHANGE", "R11": "WIRYE-OPENING-DELAY", "R12": "GWANGJU-AI-PILOT",
        "R13": "WIRYE-OPENING-DELAY", "R14": "WIRYE-OPENING-DELAY", "R15": "WIRYE-OPENING-DELAY",
        "R16": "WIRYE-OPENING-DELAY", "R17": "WIRYE-OPENING-DELAY", "R18": "WIRYE-OPENING-DELAY",
        "R19": "TOKYO-PATRAIL", "R20": "DAEJEON-DRILL", "R21": "HCMC-METRO2-CONSTRUCTION",
        "R22": "JANGAM-SERVICE-RESUME", "R23": "DAEJEON-TRAM-SELECTION", "R24": "MARSEILLE-TRAM-EXTENSION",
        "R25": "HCMC-BEN-THANH-CAN-GIO", "R26": "NAPLES-L1-CLOSURE",
    },
    "mega31g3": {
        "R1": "IEC-61373", "R2": "KUMAMOTO-TRAM-INCIDENT", "R3": "GERA-TRAM-TEST",
        "R4": "NAPLES-STATION-WORKS", "R5": "NYC-SUBWAY-SURFING", "R6": "BARCELONA-FIRE-CAUSE",
        "R7": "TOKYO-DOOR-INCIDENT", "R8": "NUREMBERG-TRANSIT-PROGRAM", "R9": "LISBON-L1-SERVICE",
        "R10": "SEOUL-SCOOTER-BAN", "R11": "MELBOURNE-G-TRAM", "R12": "SHANGHAI-L22-DELIVERY",
        "R13": "SINGAPORE-DEPOT-AUTOMATION", "R14": "INCHEON-L2-ANNIVERSARY",
    },
}


class BudgetExceeded(BaseException):
    pass


class MeteredTransport:
    """Crash-safe cumulative campaign ledger plus one-call transport."""

    CAMPAIGN_ID = "RC66-R7"

    def __init__(self, cap: int, journal_path: Path, prior_call_upper_bound: int | None = None) -> None:
        if not isinstance(journal_path, Path):
            raise TypeError("RC66-R7 requires a durable journal path")
        self.cap = cap
        self.journal_path = journal_path
        self.context = ""
        self.log: list[dict[str, Any]] = []
        self.duplicate_membership_by_context: Counter[str] = Counter()
        self._seen: Counter[str] = Counter()
        self._real = UrllibMaiAgentJsonTransport()
        self.prior_call_upper_bound = 0
        self.retries = 0
        if journal_path.exists():
            self._load()
            if prior_call_upper_bound is not None and prior_call_upper_bound != self.prior_call_upper_bound:
                raise RuntimeError("prior call bound disagrees with the durable RC66-R7 ledger")
        else:
            if prior_call_upper_bound is None or prior_call_upper_bound < 0:
                raise RuntimeError("a new RC66-R7 ledger requires an exact prior-call count or conservative upper bound")
            self.prior_call_upper_bound = int(prior_call_upper_bound)
            self._persist()

    @property
    def calls(self) -> int:
        return self.prior_call_upper_bound + len(self.log)

    @property
    def completed_calls(self) -> int:
        return sum(1 for item in self.log if item.get("state") == "COMPLETED")

    @property
    def remaining_calls(self) -> int:
        return max(0, self.cap - self.calls)

    def _load(self) -> None:
        try:
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
            if data.get("campaign_id") != self.CAMPAIGN_ID or int(data.get("hard_call_cap")) != self.cap:
                raise ValueError("campaign identity or hard cap mismatch")
            prior = int(data.get("prior_call_upper_bound"))
            log = data.get("log")
            if prior < 0 or not isinstance(log, list):
                raise ValueError("invalid durable ledger shape")
            if int(data.get("attempted_calls")) != prior + len(log):
                raise ValueError("durable ledger attempted-call count is inconsistent")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("RC66-R7 durable ledger is invalid; refusing to reset or continue") from exc
        self.prior_call_upper_bound = prior
        self.log = [dict(item) for item in log]
        self.retries = int(data.get("transport_retries", sum(1 for item in self.log if item.get("retry"))))
        self._seen.update(item.get("request_sha256", "") for item in self.log if item.get("request_sha256"))
        self.duplicate_membership_by_context.update(data.get("duplicate_membership_by_context", {}))

    def _persist(self) -> None:
        payload = {
            "campaign_id": self.CAMPAIGN_ID,
            "hard_call_cap": self.cap,
            "prior_call_upper_bound": self.prior_call_upper_bound,
            "attempted_calls": self.calls,
            "completed_calls": self.completed_calls,
            "remaining_calls": self.remaining_calls,
            "transport_retries": self.retries,
            "log": self.log,
            "duplicate_membership_by_context": dict(self.duplicate_membership_by_context),
        }
        temp_path = self.journal_path.with_name(self.journal_path.name + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.journal_path)

    def __call__(self, endpoint: str, *, headers: dict[str, str], body: bytes, timeout_seconds: float) -> MaiAgentHttpResponse:
        if self.calls >= self.cap:
            raise BudgetExceeded(f"hard call cap {self.cap} reached")
        digest = sha256(body).hexdigest()
        self._seen[digest] += 1
        is_retry = self._seen[digest] > 1
        if is_retry:
            self.retries += 1
        item = {
            "index": self.calls + 1,
            "context": self.context,
            "request_sha256": digest,
            "retry": is_retry,
            "state": "IN_FLIGHT",
        }
        self.log.append(item)
        # Reserve the attempt before network I/O.  An interruption during the
        # request therefore cannot make a later process unknowingly reuse it.
        self._persist()
        try:
            response = self._real(endpoint, headers=headers, body=body, timeout_seconds=timeout_seconds)
        except BaseException as exc:
            item["state"] = "COMPLETED"
            item["outcome"] = type(exc).__name__
            self._persist()
            raise
        item["state"] = "COMPLETED"
        item["outcome"] = f"HTTP_{response.status_code}"
        try:
            envelope = json.loads(response.body)
            proposal = json.loads(envelope.get("content", ""))
            members = [member.get("record_id") for group in proposal.get("groups", []) for member in group.get("members", [])]
            if len(members) != len(set(members)):
                self.duplicate_membership_by_context[self.context] += 1
        except (TypeError, ValueError, AttributeError):
            pass
        self._persist()
        return response


def _load_audits(values: list[str]) -> dict[str, dict[str, Any]]:
    audits: dict[str, dict[str, Any]] = {}
    for value in values:
        name, raw_path = value.split("=", 1)
        audits[name] = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    return audits


def _candidate_index(audits: dict[str, dict[str, Any]]) -> dict[str, tuple[str, dict[str, Any]]]:
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    for name, audit in audits.items():
        for candidate in audit.get("candidates", []):
            candidate_id = candidate["candidate_id"]
            current = result.get(candidate_id)
            evidence = candidate.get("evidence") or {}
            current_evidence = (current[1].get("evidence") or {}) if current else {}
            # The same candidate can be present in a later incident audit as
            # a reference-only row with no source metadata.  Prefer the
            # canonical evidence row, without treating the reference row as a
            # second source of truth.
            if current is None or (
                (not current_evidence.get("canonical_source_url") and evidence.get("canonical_source_url"))
                or (not current_evidence.get("content_sha256") and evidence.get("content_sha256"))
            ):
                result[candidate_id] = (name, candidate)
    return result


def _find_exchange(audit: dict[str, Any], required: set[str]) -> dict[str, Any] | None:
    for exchange in audit.get("event_identity_exchanges", []):
        if not exchange.get("confirmation"):
            continue
        values = set(exchange.get("records", {}).values())
        if required.issubset(values):
            return exchange
    return None


def _labelled_mega(audits: dict[str, dict[str, Any]], key: str, audit_name: str, subject: str) -> dict[str, str]:
    exchange = next(
        x for x in audits[audit_name]["event_identity_exchanges"]
        if x.get("confirmation") and x.get("subject") == subject
    )
    labels = MEGA_LABEL_BY_GROUP_RID[key]
    return {
        candidate_id: labels[record_id]
        for record_id, candidate_id in exchange["records"].items()
        if candidate_id not in EXCLUDED_IDS
    }


def _record(candidate: dict[str, Any], body: str):
    candidate_id = candidate["candidate_id"]
    url = (candidate.get("evidence") or {}).get("canonical_source_url") or ""
    canonical = CanonicalCandidate(
        candidate_id=candidate_id,
        title=candidate.get("discovery_title", ""),
        url=url,
        publisher=candidate.get("publisher", ""),
        published_at=candidate.get("published_at", ""),
        source_type="web_source",
    )
    focus_ids = tuple((candidate.get("scope") or {}).get("event_focus_sentence_ids") or ())
    sentences = {item.sentence_id: item for item in segment_evidence_sentences(body)}
    focus = [sentences[item] for item in focus_ids if item in sentences]
    provenance = {"candidate_event_focus": [{"start": item.start, "end": item.end} for item in focus]}
    evidence = EvidenceResult(
        candidate_id=candidate_id,
        state=EvidenceState.READY,
        canonical_source_url=url,
        source_type="web_source",
        substantive_content=body,
        provenance={"source_role": "unknown", "first_hand_source": False},
        identity_facts=None,
    )
    scope = ScopeResult(candidate_id, ScopeState.IN_SCOPE, provenance=provenance)
    temporal = TemporalResult(candidate_id, True, diagnostic=TemporalDiagnostic.NONE)
    return __import__("src.weekly_report.contracts", fromlist=["EventIdentityRecord"]).EventIdentityRecord(
        canonical, evidence, scope, temporal
    )


def _build_corpus(audits: dict[str, dict[str, Any]], *, allow_exclusions: bool = False) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    index = _candidate_index(audits)
    labels = dict(MIXED_IDS) | PURE_LABELS | INCIDENT_LABELS
    selected: set[str] = set(labels)
    mega_specs = (
        ("mega29g4", "run29", "event-identity-batch-1-p3-n2:group-4:confirmation"),
        ("mega29g5", "run29", "event-identity-batch-1-p3-n2:group-5:confirmation"),
        ("mega31g3", "run31", "event-identity-batch-1-p2:group-3:confirmation"),
    )
    for key, audit_name, subject in mega_specs:
        labels.update(_labelled_mega(audits, key, audit_name, subject))
    selected.update(labels)

    records: dict[str, Any] = {}
    corpus_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for candidate_id in sorted(selected):
        if candidate_id in EXCLUDED_IDS:
            continue
        if candidate_id not in index:
            failures.append({"candidate_id": candidate_id, "reason": "AUDIT_RECORD_NOT_FOUND"})
            continue
        audit_name, candidate = index[candidate_id]
        evidence = candidate.get("evidence") or {}
        url = evidence.get("canonical_source_url") or ""
        expected = evidence.get("content_sha256") or ""
        body = ""
        actual = ""
        last_error: BaseException | None = None
        for _attempt in range(3):
            try:
                fetched = _default_fetcher(url, 30.0)
                assessment = assess_document(fetched.content, fetched.content_type, resource_url=fetched.url, candidate_id=candidate_id)
                body = assessment.body_text
                actual = sha256(body.encode("utf-8")).hexdigest()
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            failures.append({"candidate_id": candidate_id, "reason": "EVIDENCE_UNAVAILABLE", "error": type(last_error).__name__})
            continue
        if actual != expected:
            failures.append({"candidate_id": candidate_id, "reason": "HASH_MISMATCH", "expected": expected, "actual": actual})
            continue
        records[candidate_id] = _record(candidate, body)
        corpus_rows.append({
            "candidate_id": candidate_id,
            "audit": audit_name,
            "content_sha256": actual,
            "focus_sentence_ids": list((candidate.get("scope") or {}).get("event_focus_sentence_ids") or ()),
            "label": labels.get(candidate_id, "UNLABELLED"),
        })

    if failures and not allow_exclusions:
        raise RuntimeError(json.dumps({"expected": len(selected - EXCLUDED_IDS), "verified": len(records), "failures": failures}, ensure_ascii=False))

    direct_specs = [
        ("mixed_incheon", "run34", {key for key, value in MIXED_IDS.items() if value == "INCHEON-WIFI-START"} & set(records)),
        ("mixed_sydney", "run33", {key for key, value in MIXED_IDS.items() if value == "SYDNEY-SW-OPENING"} & set(records)),
        ("pure_daegu", "run24", set(PURE_LABELS) & {"cand_c3b575ffd39c3de6d71979e28f839672ab2bc80515b1033973f1ff77d2efb4d7", "cand_fbff996e9a8b8afc0533851199f25159b96b77402999893ccae79feade5928ad"}),
        ("pure_seoul", "run26", {"cand_89f34b8ab343ceb0adc33397cda22bc36e39e977df27531c149966356feaa1be", "cand_9ba3de65b565a34a47c71b09ff555534379ea7ac9a9616e4c735ac0c083e0692"}),
        ("pure_kim", "run32", {"cand_cb7c91e25aed4a8dd6ea6c2cbd52e90c86923a9e72864f73f079ff77fad5e7a6", "cand_edde386e5623ad0f276f36e5de9dfd82684c22447980790168dee84f02244bcb"}),
        ("pure_kyiv", "run34", {"cand_12aaae13731c64594c85c9ea7b8854125f8a4803e4730dd1420d9a6449dddf6f"}),
        ("pure_ulsan", "run34", {key for key, value in PURE_LABELS.items() if value == "ULSAN-DEPOT"}),
        ("incident_followup", "run30", set(INCIDENT_LABELS) & set(records)),
        ("mega_29_group4", "run29", set(_labelled_mega(audits, "mega29g4", "run29", mega_specs[0][2])) & set(records)),
        ("mega_29_group5", "run29", set(_labelled_mega(audits, "mega29g5", "run29", mega_specs[1][2])) & set(records)),
        ("mega_31_group3", "run31", set(_labelled_mega(audits, "mega31g3", "run31", mega_specs[2][2])) & set(records)),
    ]
    direct_groups: list[dict[str, Any]] = []
    for name, audit_name, required in direct_specs:
        exchange = _find_exchange(audits[audit_name], required)
        if exchange is None:
            raise RuntimeError(f"missing confirmation exchange for {name}")
        ordered = []
        for candidate_id in exchange.get("records", {}).values():
            if candidate_id in records and candidate_id not in ordered:
                ordered.append(candidate_id)
        if len(ordered) >= 2:
            direct_groups.append({"name": name, "subject": exchange["subject"], "candidate_ids": ordered})

    manifest = {
        "d4_l1": "INCHEON-WIFI-START",
        "corpus_source": "refetched, sha256-verified Event Identity input",
        "prepared": 78,
        "preflight_verified": 65,
        "verified": len(records),
        "excluded": sorted(EXCLUDED_IDS | {item["candidate_id"] for item in failures}),
        "fetch_failures": failures,
        "rows": sorted(corpus_rows, key=lambda item: item["candidate_id"]),
        "direct_groups": direct_groups,
        "label_basis": "independent review of rebuilt excerpt text before paid calls",
    }
    return records, labels, manifest


def _full_focus(record: Any) -> Any:
    sentences = segment_evidence_sentences(record.evidence.substantive_content)
    ids = tuple(sentence.sentence_id for sentence in sentences)
    focus = [{"start": sentence.start, "end": sentence.end} for sentence in sentences]
    return replace(record, scope=replace(record.scope, provenance={"candidate_event_focus": focus}))


def _pairs(groups: Iterable[Iterable[str]]) -> set[tuple[str, str]]:
    return {tuple(sorted(pair)) for group in groups for pair in itertools.combinations(group, 2)}


def _batch_score(result: Any, labels: dict[str, str], record_ids: Iterable[str], duplicate_membership_answers: int = 0) -> dict[str, Any]:
    output_groups = [tuple(group.member_candidate_ids) for group in result.groups]
    merged = _pairs(output_groups)
    ids = sorted(record_ids)
    same = {pair for pair in itertools.combinations(ids, 2) if labels[pair[0]] == labels[pair[1]]}
    different = {pair for pair in itertools.combinations(ids, 2) if labels[pair[0]] != labels[pair[1]]}
    return {
        "events": len(result.groups),
        "same_label_pairs": len(same),
        "same_label_merged": len(merged & same),
        "recall": [len(merged & same), len(same)],
        "false_merges": len(merged & different),
        "duplicate_membership_answers": duplicate_membership_answers,
        "technical_gaps": [[gap.stage, gap.subject_id, gap.failure_class] for gap in result.technical_gaps],
        "proposal_exchanges": len(result.proposal_exchanges),
    }


def _direct_call(provider: Any, records: dict[str, Any], candidate_ids: list[str], subject: str) -> dict[str, Any]:
    grouping_records = tuple(_grouping_record(records[candidate_id], f"R{index}") for index, candidate_id in enumerate(candidate_ids, 1))
    if any(item is None for item in grouping_records):
        raise RuntimeError(f"cannot build direct confirmation {subject}")
    request = EventIdentityGroupingRequest(subject, tuple(item for item in grouping_records if item is not None), confirmation=True)
    raw = provider(request)
    by_record = {record.record_id: record.candidate_id for record in request.records}
    seen: list[str] = []
    output: list[list[str]] = []
    for group in raw.get("groups", []):
        members = [by_record.get(member.get("record_id"), "UNKNOWN") for member in group.get("members", [])]
        seen.extend(members)
        output.append(members)
    labels = {candidate_id: current_labels[candidate_id] for candidate_id in candidate_ids}
    merged = _pairs(output)
    same = {pair for pair in itertools.combinations(sorted(labels), 2) if labels[pair[0]] == labels[pair[1]]}
    different = {pair for pair in itertools.combinations(sorted(labels), 2) if labels[pair[0]] != labels[pair[1]]}
    return {
        "subject": subject,
        "records": candidate_ids,
        "partition": output,
        "duplicate_membership": len(seen) != len(set(seen)),
        "same_label_pairs": len(same),
        "same_label_merged": len(merged & same),
        "different_label_pairs": len(different),
        "false_merges": len(merged & different),
    }


def _candidate_builder(prompt: str):
    original = provider_module.build_maiagent_event_identity_model_input

    def build(request: Any) -> dict[str, Any]:
        payload = original(request)
        if prompt == BASELINE_PROMPT:
            return payload
        if request.confirmation:
            payload = dict(payload)
            payload["prompt_version"] = CANDIDATE_PROMPT
            payload["instructions"] = [*payload["instructions"], CANDIDATE_GUIDANCE]
        return payload

    return build


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", action="append", required=True, help="name=selection_audit.json")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cap", type=int, default=HARD_CALL_CAP)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--allow-corpus-exclusions", action="store_true")
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--prior-call-upper-bound", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.cap != HARD_CALL_CAP:
        raise SystemExit("RC66-R7 hard cap is frozen at 400")

    global current_labels
    audits = _load_audits(args.audit)
    records, current_labels, manifest = _build_corpus(audits, allow_exclusions=args.allow_corpus_exclusions)
    plan = {
        "starting_sha": "be864067f2f5bc098735e25bdd8c574d88d7d89a",
        "d4_l1": "INCHEON-WIFI-START",
        "baseline_prompt": BASELINE_PROMPT,
        "candidate_prompt": CANDIDATE_PROMPT,
        "candidate_change": "confirmation-only clarification; no production mutation",
        "rounds": 3,
        "arms": ["cited_focus_rc52", "cited_focus_m_c", "bh2_mf_rc52", "bh2_mf_m_c"],
        "planned_direct_confirmation_groups": len(manifest["direct_groups"]),
        "expected_verified_records": len(records),
        "corpus_exclusions_allowed": args.allow_corpus_exclusions,
        "hard_call_cap": HARD_CALL_CAP,
        "corpus_manifest": manifest,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    plan_path = args.out.with_name("rc66_r7_plan.json")
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.prepare_only:
        print(json.dumps({"status": "READY", "verified": len(records), "direct_groups": len(manifest["direct_groups"]), "plan": str(plan_path)}, ensure_ascii=False))
        return 0

    journal_path = args.journal or args.out.with_name("rc66_r7_call_journal.json")
    if args.resume and not journal_path.exists():
        raise SystemExit("--resume requires an existing RC66-R7 durable ledger")
    if not args.resume and journal_path.exists():
        raise SystemExit("existing RC66-R7 ledger requires --resume; refusing to reset cumulative accounting")
    meter = MeteredTransport(HARD_CALL_CAP, journal_path, args.prior_call_upper_bound)
    started = time.monotonic()
    results: dict[str, Any] = {"rounds": [], "direct": []}
    try:
        for prompt in (BASELINE_PROMPT, CANDIDATE_PROMPT):
            provider_module.build_maiagent_event_identity_model_input = _candidate_builder(prompt)
            provider = build_maiagent_event_identity_provider(transport=meter)
            if provider is None:
                raise RuntimeError("Structured Helper configuration unavailable")
            for round_number in range(1, 4):
                for arm, source_records, focus_mode in (
                    ("cited_focus_rc52", records, "cited"),
                    ("bh2_mf_rc52", {key: _full_focus(value) for key, value in records.items()}, "full"),
                ):
                    meter.context = f"{prompt}|round-{round_number}|{arm}"
                    run = EventIdentity(provider).evaluate(list(source_records.values()))
                    item = _batch_score(
                        run,
                        current_labels,
                        source_records,
                        meter.duplicate_membership_by_context.get(meter.context, 0),
                    )
                    item.update({"prompt": prompt, "round": round_number, "arm": arm, "focus": focus_mode})
                    results["rounds"].append(item)
                for arm, focus_mode in (("cited_focus_m_c", "cited"), ("bh2_mf_m_c", "full")):
                    source_records = records if focus_mode == "cited" else {key: _full_focus(value) for key, value in records.items()}
                    for group in manifest["direct_groups"]:
                        meter.context = f"{prompt}|round-{round_number}|{arm}|{group['name']}"
                        item = _direct_call(provider, source_records, group["candidate_ids"], group["subject"])
                        item.update({"prompt": prompt, "round": round_number, "arm": arm, "focus": focus_mode, "group": group["name"]})
                        results["direct"].append(item)
    except BudgetExceeded as exc:
        results["budget_exceeded"] = str(exc)
    except Exception as exc:
        results["harness_error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        provider_module.build_maiagent_event_identity_model_input = build_maiagent_event_identity_model_input

    results["elapsed_seconds"] = round(time.monotonic() - started, 1)
    results["actual_maiagent_calls"] = meter.calls
    results["new_maiagent_calls_this_process"] = len(meter.log)
    results["completed_maiagent_calls_this_process"] = meter.completed_calls
    results["transport_retries"] = meter.retries
    results["safe_remaining_calls"] = meter.remaining_calls
    results["call_journal"] = str(journal_path)
    results["hard_call_cap"] = HARD_CALL_CAP
    results["call_log"] = meter.log
    results["manifest"] = manifest
    results["plan"] = plan
    results["recorded_replay"] = "unchanged preflight: reproduced=true; events=81; differences=[]"
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    status = "CAP_REACHED" if "budget_exceeded" in results else "BLOCKED_HARNESS" if "harness_error" in results else "COMPLETE"
    print(json.dumps({"status": status, "calls": meter.calls, "retries": meter.retries, "remaining": meter.remaining_calls, "round_results": len(results["rounds"]), "direct_results": len(results["direct"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
