"""Tests for JSON schema validation — valid artifacts pass, invalid ones are rejected."""
import pytest

from chorus_ai.artifacts.validate import validate_artifact
from chorus_ai.core.errors import ChorusFatalError
from chorus_ai.tests.conftest import SOURCE_SHA, SAMPLE_FACTS


class TestIngestionRecord:
    def test_valid(self):
        validate_artifact("ingestion_record", {
            "schema_version": "v1",
            "source_doc_sha256": SOURCE_SHA,
            "text_path": "10_ingestion/document_text.txt",
        })

    def test_missing_required_field_raises(self):
        with pytest.raises(ChorusFatalError, match="SCHEMA_VALIDATION_FAILED"):
            validate_artifact("ingestion_record", {
                "schema_version": "v1",
                "source_doc_sha256": SOURCE_SHA,
                # text_path missing
            })


class TestFactList:
    def test_valid(self):
        validate_artifact("fact_list", {
            "schema_version": "v1",
            "source_doc_sha256": SOURCE_SHA,
            "fact_set_id": "FACTSET_abc",
            "facts": SAMPLE_FACTS,
        })

    def test_empty_facts_valid(self):
        validate_artifact("fact_list", {
            "schema_version": "v1",
            "source_doc_sha256": SOURCE_SHA,
            "fact_set_id": "FACTSET_abc",
            "facts": [],
        })

    def test_missing_fact_set_id_raises(self):
        with pytest.raises(ChorusFatalError, match="SCHEMA_VALIDATION_FAILED"):
            validate_artifact("fact_list", {
                "schema_version": "v1",
                "source_doc_sha256": SOURCE_SHA,
                "facts": [],
            })


class TestSummary:
    def test_valid(self):
        validate_artifact("summary", {
            "schema_version": "v1",
            "source_doc_sha256": SOURCE_SHA,
            "summary_id": "SUM_A_abc",
            "summary_text": "A summary.",
        })

    def test_missing_summary_text_raises(self):
        with pytest.raises(ChorusFatalError, match="SCHEMA_VALIDATION_FAILED"):
            validate_artifact("summary", {
                "schema_version": "v1",
                "source_doc_sha256": SOURCE_SHA,
                "summary_id": "SUM_A_abc",
                # summary_text missing
            })


class TestUnknownSchema:
    def test_unknown_name_raises(self):
        with pytest.raises(ChorusFatalError, match="UNKNOWN_SCHEMA"):
            validate_artifact("nonexistent_artifact", {})
