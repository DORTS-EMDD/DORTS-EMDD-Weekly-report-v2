"""RC-69 corrections (section A.50): proposal and declared fields are policed,
format characters are withheld, builder and audit share one length measure, a
missing gap record is explicit, and outputs are compared byte for byte.

Invisible characters are built with ``chr`` so no literal format character
sits in this source file.
"""

from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.weekly_report import category_observation, selection_audit
from src.weekly_report.category_observation import (
    AUDIT_HEADROOM,
    MAX_SERIALIZED_LENGTH,
    failure_class_value,
    observe_category_exchange,
    serialized_length,
    subtype_violation,
    unavailable_category_exchange,
)
from src.weekly_report.classifier import CategorySemanticRequest, CategorySourceEvidence
from src.weekly_report.contracts import SemanticProviderTechnicalFailure, TechnicalGap
from src.weekly_report.gmail_smtp import index_for_artifact, subject_for_artifact
from src.weekly_report.production_runner import ProductionRunner
from src.weekly_report.reportability import Reportability
from src.weekly_report.selection_audit import build_selection_audit, selection_audit_mapping_is_bounded
from src.weekly_report.taxonomy import Taxonomy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_category_exchange_observation import SENTENCE, _app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ZWSP, RLO, NBSP, IDEOGRAPHIC_SPACE, LINE_SEP, BOM = (chr(c) for c in (0x200B, 0x202E, 0xA0, 0x3000, 0x2028, 0xFEFF))
PERIOD = ("2026-09-12", "2026-09-18")


def _request(facts=None, claims=()):
    source = CategorySourceEvidence("cand-a", SENTENCE, facts if facts is not None else {"location": "Lyon"})
    return CategorySemanticRequest((source,), tuple(claims))


# Correction 1: the subtype and the enum, predicate and declared fields are policed.
@pytest.mark.parametrize(
    "value, reason",
    [
        ("fifth_generation_network_deployment", None),
        ("track_condition_monitoring_deployment", None),
        ("5g_wifi_deployment", None),
        ("x" * 129, "SIZE_BOUND"),
        ("see https://example.test", "CONTENT_BOUND"),
        ("ops@example.test", "CONTENT_BOUND"),
        ("call_0912345678", "CONTENT_BOUND"),
        ("a3f9c2d1e4b5a6f7c8d9e0f1a2b3c4d5", "CONTENT_BOUND"),
        ("api_key_leak", "CONTENT_BOUND"),
        ("Opened. Then closed", "CONTENT_BOUND"),
        ("wifi" + ZWSP, "CONTENT_BOUND"),
        ("wifi" + RLO, "CONTENT_BOUND"),
        ("wifi" + NBSP + "x", "CONTENT_BOUND"),
    ],
)
def test_the_subtype_policy(value, reason):
    assert subtype_violation(value) == reason


def test_withheld_subtypes_keep_only_marker_and_hash():
    record = observe_category_exchange(
        _request(), outcome="REJECTED",
        proposal_payload={"category_state": "CATEGORY_ASSIGNED", "primary_category_id": "TECHNICAL_DEVELOPMENT",
                          "subtype": "see https://leak.example.test", "category_resolution_reason": None, "citations": []},
        predicate="SUBTYPE_FORMAT",
    )
    subtype = record["proposal"]["subtype_raw"]
    assert set(subtype) == {"withheld", "sha256"} and subtype["withheld"] == "CONTENT_BOUND"
    assert "leak.example.test" not in json.dumps(record, ensure_ascii=False)


def test_enum_predicate_and_declared_fields_are_allowlisted():
    record = observe_category_exchange(
        _request(), outcome="REJECTED",
        proposal_payload={"category_state": "Please visit https://x.test", "primary_category_id": "TECHNICAL_DEVELOPMENT",
                          "subtype": None, "category_resolution_reason": "free text from the model", "citations": []},
        provider_provenance={"provider_identifier": "maiagent-chatbot-completions", "prompt_version": "Bearer abc123",
                             "schema_version": "category-proposal-v5", "helper_version": "maiagent-chatbot-adapter-v2",
                             "model_identifier": "sk-live-0123456789abcdefghijklmn"},
        predicate="SOMETHING ELSE",
        category_result_state="NOT A STATE",
    )
    rendered = json.dumps(record, ensure_ascii=False)
    assert record["proposal"]["primary_category_id"] == "TECHNICAL_DEVELOPMENT"
    assert record["proposal"]["category_state"]["withheld"] == "NOT_ALLOWLISTED"
    assert record["proposal"]["category_resolution_reason"]["withheld"] == "NOT_ALLOWLISTED"
    assert record["validation"]["predicate"]["withheld"] == "NOT_ALLOWLISTED"
    assert record["validation"]["category_result_state"]["withheld"] == "NOT_ALLOWLISTED"
    declared = record["provider_declared"]
    assert declared["provider_identifier"] == "maiagent-chatbot-completions"
    assert declared["schema_version"] == "category-proposal-v5"
    assert declared["message_version"]["withheld"] == "NOT_IDENTIFIER"
    assert declared["model_identifier"]["withheld"] == "NOT_IDENTIFIER"
    for leak in ("https://x.test", "free text", "Bearer", "sk-live", "SOMETHING", "NOT A STATE"):
        assert leak not in rendered
    assert failure_class_value("TIMEOUT") == "TIMEOUT"
    assert failure_class_value("timeout sk-0123")["withheld"] == "NOT_IDENTIFIER"


# Correction 2: format characters in action_facts and claims are withheld.
@pytest.mark.parametrize("character", [ZWSP, RLO, NBSP, IDEOGRAPHIC_SPACE, LINE_SEP, BOM])
def test_format_characters_in_action_facts_are_withheld(character):
    record = observe_category_exchange(_request({"location": "Ly" + character + "on"}), outcome="ACCEPTED")
    location = record["semantic_request"]["action_facts"]["M1"]["location"]
    assert location["withheld"] == "CONTENT_BOUND"
    assert record["semantic_request"]["input_exposure"] == "WITHHELD"
    assert character not in json.dumps(record, ensure_ascii=False)


def test_unusual_input_shapes_cannot_leak():
    record = observe_category_exchange(
        _request(
            {"location": "Lyon", "source_claims": "a plain string, not a mapping", "future_key": "https://x.test"},
            claims=(("country", (("cand-a", "see https://claim.test"),)), ("Bad Key!", (("cand-a", "FR"),))),
        ),
        outcome="ACCEPTED",
        proposal_payload={
            "category_state": "CATEGORY_ASSIGNED", "primary_category_id": "TECHNICAL_DEVELOPMENT", "subtype": "x",
            "category_resolution_reason": None,
            "citations": [{"source_ref": "M1", "sentence_ids": [f"S{i}" for i in range(1, 46)] + [7, "bad"]}] * 10,
        },
    )
    rendered = json.dumps(record, ensure_ascii=False)
    for leak in ("a plain string", "https://x.test", "claim.test", "Bad Key!"):
        assert leak not in rendered
    request = record["semantic_request"]
    assert request["input_exposure"] == "WITHHELD"
    assert [entry["withheld"] for entry in request["action_facts"]["M1"]["withheld_keys"]] == ["KEY_NOT_ALLOWED", "KEY_NOT_ALLOWED"]
    assert request["unresolved_event_claims"][0]["source_values"][0]["value"]["withheld"] == "CONTENT_BOUND"
    assert request["unresolved_event_claims"][1]["claim_key"]["withheld"] == "KEY_NOT_ALLOWED"
    citations = record["proposal"]["citations"]
    assert len(citations) == 8 and record["proposal"]["citations_omitted"] == 2
    assert len(citations[0]["sentence_ids"]) == 40 and citations[0]["omitted_sentence_ids"] == 7


# Correction 4: one length measure; the builder leaves room for the audit's addition.
def test_builder_and_audit_share_one_length_measure():
    assert selection_audit.serialized_length is category_observation.serialized_length
    largest = None
    count = 0
    while True:
        count += 20
        claims = tuple((f"claim_{index}", (("cand-a", "Lyon"),)) for index in range(count))
        record = observe_category_exchange(_request(claims=claims), outcome="NO_PROPOSAL")
        if record["observation_status"] == "UNAVAILABLE":
            assert record["observation_error"] == "SIZE_BOUND"
            break
        largest = record
    assert largest is not None
    assert serialized_length(largest) <= MAX_SERIALIZED_LENGTH - AUDIT_HEADROOM
    largest["validation"]["technical_failure_class"] = "X" * 64
    assert serialized_length(largest) <= MAX_SERIALIZED_LENGTH
    audit = {"candidates": [], "events": [{"category_exchange": largest}]}
    assert selection_audit_mapping_is_bounded(audit)


# Correction 7: a Category gap without a record is explicit.
def test_a_gap_without_a_record_is_shown_as_not_attached():
    result = _app().run("selected")
    event_id = result.category_results[0].event_id
    gap = TechnicalGap.from_failure("Category", event_id, SemanticProviderTechnicalFailure("TIMEOUT", attempts=2, transient=True))
    view = SimpleNamespace(**{item.name: getattr(result, item.name) for item in fields(result)})
    view.category_results = tuple(item for item in result.category_results if item.event_id != event_id)
    view.technical_gaps = result.technical_gaps + (gap,)
    view.category_gap_exchanges = ()
    projected = next(o for o in build_selection_audit(view)["events"] if o["event_id"] == event_id)["category_exchange"]
    assert projected == unavailable_category_exchange("OBSERVATION_NOT_ATTACHED")


# Correction 6: byte-level comparisons of outputs and owner inputs.
def _runs():
    healthy = ProductionRunner(_app()).run(period_start=PERIOD[0], period_end=PERIOD[1])
    with patch.object(category_observation, "observe_category_exchange", side_effect=RuntimeError("observer broke")):
        broken = ProductionRunner(_app()).run(period_start=PERIOD[0], period_end=PERIOD[1])
    return healthy, broken


def _cli(result, directory):
    sys.path.insert(0, str(ROOT))
    import main

    class _Runner:
        @classmethod
        def from_environment(cls):
            return cls()

        def run(self, **_):
            return result

    argv = ["--region-mode", "selected", "--period-start", PERIOD[0], "--period-end", PERIOD[1], "--output-dir", str(directory)]
    with patch.object(main, "ProductionRunner", _Runner), patch("weekly_report.pdf_renderer.render_report_pdf", return_value=b"%PDF-stub"):
        return main._main(argv)


def test_markdown_bytes_cli_exit_code_and_email_text_are_identical(tmp_path, capsys):
    healthy, broken = _runs()
    healthy_code = _cli(healthy, tmp_path / "healthy")
    broken_code = _cli(broken, tmp_path / "broken")
    capsys.readouterr()
    assert healthy_code == broken_code
    name = f"{healthy.final_report.report_id}.md"
    assert (tmp_path / "healthy" / name).read_bytes() == (tmp_path / "broken" / name).read_bytes()
    assert subject_for_artifact(healthy.final_report).encode("utf-8") == subject_for_artifact(broken.final_report).encode("utf-8")
    assert json.dumps(index_for_artifact(healthy.final_report), ensure_ascii=False).encode("utf-8") == json.dumps(
        index_for_artifact(broken.final_report), ensure_ascii=False
    ).encode("utf-8")


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")


def test_writer_taxonomy_and_reportability_inputs_are_byte_identical():
    from test_execution_trace import _full_app

    def run(broken):
        app, calls = _full_app()
        app._classifier = _app()._classifier
        if broken:
            with patch.object(category_observation, "observe_category_exchange", side_effect=RuntimeError("observer broke")):
                result = app.run("selected")
        else:
            result = app.run("selected")
        return result, calls

    healthy, healthy_calls = run(False)
    _, broken_calls = run(True)
    assert healthy_calls and _canonical(healthy_calls) == _canonical(broken_calls)

    taxonomy_requests: list[bytes] = []
    reportability_requests: list[bytes] = []

    def taxonomy_provider(request):
        taxonomy_requests.append(_canonical(request.as_payload()))
        raise RuntimeError("captured")

    def reportability_provider(request):
        reportability_requests.append(_canonical(request.as_payload()))
        raise RuntimeError("captured")

    variants = (
        lambda provenance: provenance,
        lambda provenance: {**provenance, "semantic_exchange": unavailable_category_exchange()},
        lambda provenance: {key: value for key, value in provenance.items() if key != "semantic_exchange"},
    )
    for flow in healthy.downstream_results:
        decision = flow.decision
        for variant in variants:
            category = replace(decision.category_result, provenance=variant(dict(decision.category_result.provenance)))
            try:
                Taxonomy(taxonomy_provider).evaluate(decision.event_group, decision.member_records, category)
            except Exception:  # noqa: BLE001 - only the captured request matters
                pass
            try:
                Reportability(reportability_provider).evaluate(replace(decision, category_result=category))
            except Exception:  # noqa: BLE001
                pass
        taxonomy_set = taxonomy_requests[-3:]
        reportability_set = reportability_requests[-3:]
        assert len(taxonomy_set) == len(reportability_set) == 3
        assert len(set(taxonomy_set)) == 1 and len(set(reportability_set)) == 1


def test_no_other_module_reads_category_provenance():
    # Section A.50: only the Classifier writes CategoryResult.provenance and only
    # the selection audit reads it; no owner, entry point or script touches it.
    import re

    reader = re.compile(r"category_result[s]?\b[^\n]*\.provenance|\.provenance\b[^\n]*semantic_exchange")
    allowed = {"classifier.py", "selection_audit.py", "category_observation.py"}
    paths = list((ROOT / "src" / "weekly_report").glob("*.py")) + [ROOT / "main.py", ROOT / "streamlit_app.py"]
    paths += list((ROOT / "scripts").glob("*.py"))
    for path in paths:
        if path.name in allowed or not path.exists():
            continue
        assert not reader.search(path.read_text(encoding="utf-8")), f"{path.name} reads Category provenance"
