"""Credential-free document budgets, shared with isolated workers.

Source bytes, ZIP expansion, worker resources and delivery are distinct limits.
Operators may lower the PPTX source ceiling; raising the hard ceiling requires
new isolation/resource evidence. No original-delivery settings belong here.
"""

SOURCE_BYTES = 10_000_000
LOCAL_IMPORT_BYTES = 25_000_000
PPTX_SOURCE_BYTES = 32 * 1024 * 1024
PPTX_EXPANDED_BYTES = 64 * 1024 * 1024
PPTX_MEMBER_BYTES = 32 * 1024 * 1024
PPTX_XML_BYTES = 4 * 1024 * 1024
PPTX_MEMBERS = 4096
PPTX_RATIO = 200
PPTX_SLIDES = 200
PPTX_AUX_TEXT = 32_000
PPTX_RESPONSE_SLIDES = 8


def source_limit(kind):
    return PPTX_SOURCE_BYTES if kind == "pptx" else SOURCE_BYTES


def local_import_limit(kind):
    return min(LOCAL_IMPORT_BYTES, source_limit(kind))


class PresentationLimit(ValueError):
    """Only numeric diagnostics cross the untrusted worker boundary."""

    def __init__(self, budget, observed, limit):
        super().__init__("pptx_expansion_limit")
        self.details = {"budget": budget, "observed": observed, "limit": limit}
