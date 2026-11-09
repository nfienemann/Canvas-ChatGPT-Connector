import hashlib
import json

import pytest

from canvas_bridge.approval_admin import restore_reviewed_file_text_digest, seal_evidence
from canvas_bridge.egress_models import ContentReview


def fixture(changes=None):
    source = dict(
        source_id="fictional-file",
        version="a" * 64,
        content_sha256="b" * 64,
        rights_reference="fictional permission",
        reviewed_text_sha256="c" * 64,
    )
    source.update(changes or {})
    key = b"k" * 32
    sealed = seal_evidence(json.dumps({"sources": [source]}).encode(), key)
    review = ContentReview(
        source_id="fictional-file",
        version="a" * 64,
        content_sha256="b" * 64,
        classification="INSTRUCTOR_OWNED_COURSE_CONTENT",
        purposes={"document_reading"},
        reviewed_channels={"text"},
        privacy_reviewed_channels={"text"},
        privacy_review_reference="Local operator text review; encrypted evidence "
        + hashlib.sha256(sealed).hexdigest(),
        content_owner_permission_reference="fictional permission",
    )
    return review, sealed, key


def test_restore_only_the_original_binding_without_expanding_review():
    review, sealed, key = fixture()
    repaired = restore_reviewed_file_text_digest(review, sealed, key)
    assert repaired.extracted_text_sha256 == "c" * 64
    assert review.extracted_text_sha256 is None
    assert repaired.model_dump(exclude={"extracted_text_sha256"}) == review.model_dump(
        exclude={"extracted_text_sha256"}
    )
    assert restore_reviewed_file_text_digest(repaired, sealed, key) == repaired


@pytest.mark.parametrize(
    "change",
    [
        {"source_id": "other"},
        {"version": "d" * 64},
        {"content_sha256": "d" * 64},
        {"rights_reference": "other"},
        {"reviewed_text_sha256": "invalid"},
    ],
)
def test_mismatched_evidence_cannot_create_a_binding(change):
    with pytest.raises(ValueError):
        restore_reviewed_file_text_digest(*fixture(change))


def test_changed_evidence_is_rejected():
    review, sealed, key = fixture()
    with pytest.raises(ValueError):
        restore_reviewed_file_text_digest(review, sealed + b" ", key)
