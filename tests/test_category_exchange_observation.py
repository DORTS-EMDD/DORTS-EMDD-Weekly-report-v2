"""RC-69 (section A.50): the Category exchange observer record is observer-only.

These tests lock the approved acceptance list: decisions, technical gaps,
report output and exit status do not depend on the record; one bounded schema
covers every path; the exposure policy keeps article text, guidance text,
credentials and provider metadata out of the public audit; the fingerprint is
the semantic request's only; and nothing but the selection audit reads it.
"""

from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.weekly_report import category_observation, classifier as classifier_module
from src.weekly_report.category_observation import (
    MAX_SERIALIZED_LENGTH,
    REPLAY_SCOPE,
    exposure_violation,
    observe_category_exchange,
    semantic_request_fingerprint,
)
from src.weekly_report.category_semantic_provider import (
    CATEGORY_SEMANTIC_PROMPT_VERSION,
    MaiAgentCategorySemanticProvider,
)
from src.weekly_report.classifier import (
    CategoryProposalViolation,
    CategorySemanticHelperResult,
    CategorySemanticRequest,
    CategorySourceEvidence,
    Classifier,
    InvalidCategorySemanticResponse,
)
from src.weekly_report.contracts import (
    CategoryState,
    SemanticProviderTechnicalFailure,
    TechnicalGap,
)
from src.weekly_report.production_runner import ProductionRunner
from src.weekly_report.selection_audit import build_selection_audit, selection_audit_mapping_is_bounded

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_classifier_golden import GOLDEN, _GoldenSemanticOracle, _materialize_groups, _materialize_record  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = json.loads((GOLDEN / "category_boundary_manifest.json").read_text(encoding="utf-8"))
LOCKED = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
TOP_LEVEL_KEYS = {
    "observation_schema", "observation_status", "observation_error", "replay_scope",
    "semantic_request", "provider_declared", "proposal", "validation",
}
PROVENANCE = {
    "provider_identifier": "maiagent",
    "prompt_version": "category-full-response-contract-v2",
    "schema_version": "category-proposal-v5",
    "helper_version": "maiagent-chatbot-adapter-v2",
}


def _fixture(case_id: str) -> dict:
    for manifest in (BOUNDARY, LOCKED):
        for entry in manifest["cases"]:
            if entry["case_id"] == case_id:
                return json.loads((GOLDEN / entry["file"]).read_text(encoding="utf-8"))
    raise KeyError(case_id)


def _group(case_id: str):
    fixture = _fixture(case_id)
    records = tuple(_materialize_record(candidate) for candidate in fixture["candidates"])
    return _materialize_groups(fixture, records)[0], records


def _proposal(request, **overrides):
    # RC-80 (section A.61): the helper proposes a principal action.
    proposal = {
        "principal_action": "TECHNOLOGY_TRIAL_OR_DEPLOYMENT",
        "unresolved_reason": None,
        "subtype": "fifth_generation_network_deployment", "announced_opening_date": None,
        "citations": [{"source_ref": next(iter(request.source_refs)), "sentence_ids": ["S1"]}],
    }
    proposal.update(overrides)
    return CategorySemanticHelperResult(proposal=proposal, provenance=PROVENANCE)


def _decision(result):
    return (
        result.category_state, result.primary_category_id, result.subtype,
        result.category_resolution_reason, result.classification_reason, result.event_id,
    )


def _outcome(helper, case_id="G101"):
    group, records = _group(case_id)
    try:
        result = Classifier(helper).classify(group, records)
    except Exception as failure:  # noqa: BLE001 - the failure itself is the outcome
        gap = TechnicalGap.from_failure("Category", group.event_id, failure)
        return ("RAISED", type(failure), gap.kind, gap.failure_class), getattr(failure, "category_exchange", None)
    return ("RESULT", _decision(result)), result.provenance.get("semantic_exchange")


def _paths():
    def accepted(request):
        return _proposal(request)

    def unresolved(request):
        return _proposal(request, principal_action="PROJECT_STEP", subtype=None)

    def subtype_format(request):
        return _proposal(request, subtype="5g_wifi_deployment")

    def citation_invalid(request):
        return _proposal(request, citations=[{"source_ref": "M9", "sentence_ids": ["S1"]}])

    def response_shape(request):
        return CategorySemanticHelperResult(proposal={"principal_action": "TECHNOLOGY_TRIAL_OR_DEPLOYMENT"}, provenance=PROVENANCE)

    def helper_rejects(request):
        raise InvalidCategorySemanticResponse("unparseable proposal", provenance=PROVENANCE, predicate="RESPONSE_SHAPE")

    def technical(request):
        raise SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True, task="category_semantic_proposal")

    def generic(request):
        raise LookupError("helper broke")

    return {
        "accepted": accepted, "unresolved": unresolved, "subtype_format": subtype_format,
        "citation_invalid": citation_invalid, "response_shape": response_shape,
        "helper_rejects": helper_rejects, "technical": technical, "generic": generic, "no_helper": None,
    }


# 1. Decisions and technical gaps do not depend on the observer.
def test_golden_category_decisions_are_identical_with_the_observer_unavailable():
    cases = [entry["case_id"] for entry in BOUNDARY["cases"]] + [entry["case_id"] for entry in LOCKED["cases"]]
    checked = 0
    for case_id in cases:
        fixture = _fixture(case_id)
        expected = fixture["expected"]
        if expected.get("category_state") not in {"CATEGORY_ASSIGNED", "CATEGORY_UNRESOLVED"}:
            continue
        records = tuple(_materialize_record(candidate) for candidate in fixture["candidates"])
        groups = _materialize_groups(fixture, records)
        if len(groups) != 1:
            continue
        member_records = tuple(r for r in records if r.candidate.candidate_id in groups[0].member_candidate_ids)
        normal = Classifier(_GoldenSemanticOracle(expected)).classify(groups[0], member_records)
        with patch.object(category_observation, "observe_category_exchange", side_effect=RuntimeError("observer broke")):
            broken = Classifier(_GoldenSemanticOracle(expected)).classify(groups[0], member_records)
        assert _decision(normal) == _decision(broken), case_id
        assert broken.provenance["semantic_exchange"]["observation_status"] == "UNAVAILABLE"
        checked += 1
    assert checked >= 18


# 2. Fault injection on every path.
@pytest.mark.parametrize("path", sorted(_paths()))
def test_an_observer_failure_changes_no_result_gap_or_exception(path):
    helper = _paths()[path]
    normal, record = _outcome(helper)
    with patch.object(category_observation, "observe_category_exchange", side_effect=RuntimeError("observer broke")):
        broken, broken_record = _outcome(helper)
    with patch.object(category_observation, "_semantic_request", side_effect=RuntimeError("section broke")):
        partial, partial_record = _outcome(helper)
    assert normal == broken == partial
    assert record is not None and record["observation_status"] == "COMPLETE"
    assert broken_record["observation_status"] == "UNAVAILABLE"
    assert partial_record["observation_status"] == "PARTIAL" and partial_record["semantic_request"] is None


def test_the_technical_failure_is_reraised_as_the_same_object():
    group, records = _group("G101")
    failure = SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True)

    def helper(request):
        raise failure

    with pytest.raises(SemanticProviderTechnicalFailure) as raised:
        Classifier(helper).classify(group, records)
    assert raised.value is failure
    assert failure.category_exchange["validation"]["outcome"] == "NO_PROPOSAL"


# 3. Report output, downstream results and exit status do not change.
class _ScriptedClassifier(Classifier):
    """The real Classifier with a scripted helper, recording its calls."""

    def __init__(self):
        def helper(request):
            return _proposal(request, subtype="scripted_subtype")

        super().__init__(helper)
        self.calls = []

    def classify(self, event_group, records, *, report_period=None):
        self.calls.append(event_group)
        return super().classify(event_group, records)


def _app():
    from test_execution_trace import _full_app

    app, _ = _full_app()
    app._classifier = _ScriptedClassifier()
    return app


def _observable(result):
    # ValidationResult embeds the decision records (and so CategoryResult with
    # its provenance); compare what it validated and emitted instead.
    validation = result.validation_result
    return (
        [_decision(item) for item in result.category_results],
        [(flow.taxonomy_result, flow.reportability_result) for flow in result.downstream_results],
        result.formal_metadata, result.writer_blocks,
        validation.formal_metadata, [item.metadata for item in validation.passed], validation.failed,
        validation.correction_calls, result.final_report, result.technical_gaps,
    )


def test_report_output_and_downstream_results_do_not_depend_on_the_observer():
    normal = _app().run("selected")
    with patch.object(category_observation, "observe_category_exchange", side_effect=RuntimeError("observer broke")):
        broken = _app().run("selected")
    with patch.object(category_observation, "_build", side_effect=RuntimeError("builder broke")):
        unavailable = _app().run("selected")
    assert normal.category_results, "the real Classifier must have run"
    assert all("semantic_exchange" in item.provenance for item in normal.category_results)
    assert _observable(normal) == _observable(broken) == _observable(unavailable)
    healthy = ProductionRunner(_app()).run(period_start="2026-09-12", period_end="2026-09-18")
    with patch.object(category_observation, "observe_category_exchange", side_effect=RuntimeError("observer broke")):
        degraded = ProductionRunner(_app()).run(period_start="2026-09-12", period_end="2026-09-18")
    assert healthy.status == degraded.status
    assert healthy.final_report == degraded.final_report
    assert healthy.stage_counts == degraded.stage_counts


# 4. One bounded schema for every path.
def test_every_path_uses_the_same_record_keys():
    records = {path: _outcome(helper)[1] for path, helper in _paths().items()}
    assert all(set(record) == TOP_LEVEL_KEYS for record in records.values())
    request_keys = {frozenset(r["semantic_request"]) for r in records.values()}
    declared_keys = {frozenset(r["provider_declared"]) for r in records.values()}
    validation_keys = {frozenset(r["validation"]) for r in records.values()}
    assert len(request_keys) == len(declared_keys) == len(validation_keys) == 1
    proposals = {frozenset(r["proposal"]) for r in records.values() if r["proposal"] is not None}
    assert len(proposals) == 1
    assert records["subtype_format"]["validation"] == {
        "outcome": "REJECTED", "predicate": "SUBTYPE_FORMAT",
        "technical_failure_class": None, "category_result_state": None,
    }
    assert records["subtype_format"]["proposal"]["subtype_raw"] == "5g_wifi_deployment"
    assert records["citation_invalid"]["validation"]["predicate"] == "CITATION_INVALID"
    assert records["citation_invalid"]["proposal"]["citations"] == [
        {"source_ref": "M9", "sentence_ids": ["S1"], "omitted_sentence_ids": 0}
    ]
    assert records["accepted"]["validation"]["outcome"] == "ACCEPTED"
    assert records["accepted"]["validation"]["category_result_state"] == "CATEGORY_ASSIGNED"
    assert records["unresolved"]["validation"]["category_result_state"] == "CATEGORY_UNRESOLVED"
    for path in ("technical", "generic", "no_helper", "helper_rejects"):
        assert records[path]["proposal"] is None
    assert records["technical"]["validation"]["outcome"] == "NO_PROPOSAL"


# 5. Exposure policy.
def _request(*sources, unresolved=()):
    return CategorySemanticRequest(tuple(sources), tuple(unresolved))


SENTENCE = "The operator launched 5G Wi-Fi on every train of its two operating lines on Tuesday."


@pytest.mark.parametrize(
    "value, reason",
    [
        ("Lyon", None),
        ("서울", None),
        ("signal tests", None),
        (SENTENCE, "SIZE_BOUND"),
        ("x" * 81, "SIZE_BOUND"),
        ("Opened. Then closed", "CONTENT_BOUND"),
        ("see https://example.test", "CONTENT_BOUND"),
        ("ops@example.test", "CONTENT_BOUND"),
        ("+886 2 2181 2345", "CONTENT_BOUND"),
        ("10.0.0.12", "CONTENT_BOUND"),
        ("abcdefghijklmnopqrstuvwxyz123456", "CONTENT_BOUND"),
        ("Api-Key 1234", "CONTENT_BOUND"),
        ("line\nbreak", "CONTENT_BOUND"),
        (12, "CONTENT_BOUND"),
        ("Ly\u200bon", "CONTENT_BOUND"),
        ("Ly\u202eon", "CONTENT_BOUND"),
        ("Saint\u00a0Denis", "CONTENT_BOUND"),
        ("東京\u3000駅", "CONTENT_BOUND"),
        ("a\u2028b", "CONTENT_BOUND"),
        ("\ufeffLyon", "CONTENT_BOUND"),
    ],
)
def test_the_exposure_policy(value, reason):
    assert exposure_violation(value, (SENTENCE,)) == reason


def test_withheld_values_keep_only_a_hash_and_mark_the_input_withheld():
    short_sentence = "Trains run."
    request = _request(
        CategorySourceEvidence("cand-a", f"{short_sentence} {SENTENCE}", {"location": "Lyon", "subject": short_sentence, "unexpected": "x"}),
    )
    record = observe_category_exchange(request, outcome="ACCEPTED")
    facts = record["semantic_request"]["action_facts"]["M1"]
    assert facts["location"] == "Lyon"
    assert facts["subject"] == {"withheld": "CONTENT_BOUND", "sha256": sha256(short_sentence.encode()).hexdigest()}
    assert facts["withheld_keys"][0]["withheld"] == "KEY_NOT_ALLOWED"
    assert record["semantic_request"]["input_exposure"] == "WITHHELD"
    clean = observe_category_exchange(_request(CategorySourceEvidence("cand-a", SENTENCE, {"location": "Lyon"})), outcome="ACCEPTED")
    assert clean["semantic_request"]["input_exposure"] == "FULL"


# 6. No article text, guidance text, credentials or provider metadata.
def test_the_record_carries_no_source_text_guidance_or_secrets():
    long_text = " ".join(f"Sentence number {index} describes the signalling works at the depot in detail." for index in range(30))
    request = _request(CategorySourceEvidence("cand-a", long_text, {"location": "Lyon"}))
    leaky = dict(PROVENANCE, api_key="sk-test-0123456789abcdefghijkl", chatbot_id="chatbot-secret-id", api_base="https://api.secret.test")
    record = observe_category_exchange(
        request, outcome="ACCEPTED", provider_provenance=leaky,
        proposal_payload={"principal_action": "TECHNOLOGY_TRIAL_OR_DEPLOYMENT", "unresolved_reason": None,
                          "subtype": "x", "announced_opening_date": None,
                          "citations": [{"source_ref": "M1", "sentence_ids": ["S1", "S2", "bad id"]}]},
    )
    rendered = json.dumps(record, ensure_ascii=False)
    for sentence in long_text.split(". "):
        if len(sentence) >= 20:
            assert sentence not in rendered
    for line in classifier_module._CATEGORY_GUIDANCE:
        assert line[:40] not in rendered
    for secret in ("sk-test", "chatbot-secret-id", "api.secret.test", "api_key", "chatbot_id"):
        assert secret not in rendered
    assert record["proposal"]["citations"][0] == {"source_ref": "M1", "sentence_ids": ["S1", "S2"], "omitted_sentence_ids": 1}


# 7. The fingerprint is the semantic request's.
def test_the_semantic_request_fingerprint():
    def build(guidance=None, text=SENTENCE, facts=None, claims=(), candidate="cand-a"):
        source = CategorySourceEvidence(candidate, text, facts if facts is not None else {"location": "Lyon"})
        request = _request(source, unresolved=claims)
        if guidance is None:
            return request, observe_category_exchange(request, outcome="ACCEPTED")
        with patch.object(classifier_module, "_CATEGORY_GUIDANCE", guidance):
            return request, observe_category_exchange(request, outcome="ACCEPTED")

    request, record = build()
    canonical = json.dumps(request.as_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = sha256(canonical.encode("utf-8")).hexdigest()
    fingerprint = record["semantic_request"]["semantic_request_fingerprint_sha256"]
    assert fingerprint == expected == semantic_request_fingerprint(request.as_payload())
    assert build()[1]["semantic_request"]["semantic_request_fingerprint_sha256"] == fingerprint
    variants = [
        build(guidance=classifier_module._CATEGORY_GUIDANCE + ("One more line.",)),
        build(text=SENTENCE + " Another sentence."),
        build(facts={"location": "Paris"}),
        build(claims=(("country", (("cand-a", "FR"),)),)),
    ]
    # Candidate IDs are not in the semantic payload (sources are M1, M2, ...);
    # the record keeps the candidate-to-ref mapping in ``sources`` instead.
    other = build(candidate="cand-b")[1]["semantic_request"]
    assert other["semantic_request_fingerprint_sha256"] == fingerprint
    assert other["sources"][0]["candidate_id"] == "cand-b"
    assert all(variant[1]["semantic_request"]["semantic_request_fingerprint_sha256"] != fingerprint for variant in variants)
    assert record["semantic_request"]["category_prompt_version"] == CATEGORY_SEMANTIC_PROMPT_VERSION == "category-principal-action-v12"


# 8. Replay terminology: input-equivalent semantic replay only.
def test_the_record_declares_input_equivalent_semantic_replay_only():
    request = _request(CategorySourceEvidence("cand-a", SENTENCE, {"location": "Lyon"}))
    record = observe_category_exchange(request, outcome="ACCEPTED", provider_provenance=MaiAgentCategorySemanticProvider._provenance())
    assert record["replay_scope"] == REPLAY_SCOPE == "INPUT_EQUIVALENT_SEMANTIC_ONLY"
    assert record["provider_declared"]["model_identifier"] is None
    assert record["provider_declared"]["inference_parameters"] is None
    assert "exact" not in json.dumps(record).lower()


# 9. Only the selection audit reads the record.
def test_only_the_observer_modules_name_the_record():
    allowed = {
        "semantic_exchange": {"category_observation.py", "classifier.py", "selection_audit.py"},
        "category_exchange": {"category_observation.py", "classifier.py", "report_application.py", "selection_audit.py"},
        "category_gap_exchanges": {"report_application.py", "selection_audit.py"},
        "category_observation": {"classifier.py", "selection_audit.py", "category_observation.py"},
    }
    for source in (ROOT / "src" / "weekly_report").glob("*.py"):
        text = source.read_text(encoding="utf-8")
        for name, files in allowed.items():
            if name in text:
                assert source.name in files, f"{source.name} names observer-only {name}"


# 10. Bounds and the audit projection.
def test_the_audit_projects_the_record_once_per_event_and_stays_bounded():
    result = _app().run("selected")
    audit = build_selection_audit(result)
    assert audit["audit_version"] == "selection-audit-v4"
    assert selection_audit_mapping_is_bounded(audit)
    exchanges = [outcome["category_exchange"] for outcome in audit["events"] if outcome.get("category_exchange")]
    assert exchanges and all(record["validation"]["outcome"] == "ACCEPTED" for record in exchanges)
    assert all("category_exchange" not in entry.get("event", {}) for entry in audit["candidates"])
    oversized = json.loads(json.dumps(audit))
    oversized["events"][0]["category_exchange"] = {"padding": "x" * (MAX_SERIALIZED_LENGTH + 1)}
    assert not selection_audit_mapping_is_bounded(oversized)


def test_a_gap_record_reaches_the_audit_with_its_failure_class():
    result = _app().run("selected")
    event_id = result.category_results[0].event_id
    gap = TechnicalGap.from_failure(
        "Category", event_id, SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True)
    )
    record = observe_category_exchange(
        CategorySemanticRequest((CategorySourceEvidence("cand-a", SENTENCE, {}),)), outcome="NO_PROPOSAL"
    )
    view = SimpleNamespace(**{item.name: getattr(result, item.name) for item in fields(result)})
    view.category_results = tuple(item for item in result.category_results if item.event_id != event_id)
    view.technical_gaps = result.technical_gaps + (gap,)
    view.category_gap_exchanges = ((event_id, record),)
    audit = build_selection_audit(view)
    projected = next(outcome for outcome in audit["events"] if outcome["event_id"] == event_id)["category_exchange"]
    assert projected["validation"]["outcome"] == "NO_PROPOSAL"
    assert projected["validation"]["technical_failure_class"] == "TIMEOUT"


def test_the_report_application_carries_a_gap_record():
    app = _app()

    def helper(request):
        return _proposal(request, subtype="5g_bad")

    app._classifier = Classifier(helper)
    result = app.run("selected")
    assert result.category_gap_exchanges
    event_id, record = result.category_gap_exchanges[0]
    assert any(gap.stage == "Category" and gap.subject_id == event_id and gap.failure_class == "SUBTYPE_FORMAT" for gap in result.technical_gaps)
    assert record["proposal"]["subtype_raw"] == "5g_bad"


# 11. The job-log echo never prints the record.
def test_the_workflow_echo_does_not_print_the_record():
    workflow = (ROOT / ".github" / "workflows" / "weekly-report.yml").read_text(encoding="utf-8")
    assert "category_exchange" not in workflow
    assert "semantic_exchange" not in workflow


# 12. No prompt or decision-rule change.
def test_the_category_prompt_is_unchanged():
    assert CATEGORY_SEMANTIC_PROMPT_VERSION == "category-principal-action-v12"
    assert CategoryProposalViolation("x", "SUBTYPE_FORMAT").failure_class == "SUBTYPE_FORMAT"
    assert CategoryState.CATEGORY_ASSIGNED.value == "CATEGORY_ASSIGNED"
