"""Find one cited span in the stored transcription, preserving source offsets."""

import re

from canvas_bridge.domain import DomainError

# Restricted English glyph confusions. One same-line split is allowed, but no
# stemming, arbitrary edits, prefix matching or joins across reading lines.
_CONFUSIONS = ("ar", "nm", "il", "oc", "uv")
_WORD = re.compile(r"\b[a-zA-Z]+\b")
OCR_WARNING = "OCR can omit or misread words. Inspect the cited PDF page with render_course_file_page using file_id, page and content_hash as expected_hash."


def is_ocr_text(page):
    return page.get("state") == "ocr_extracted" or page.get("ocr_status") == "extracted"


def uncertain_page(page):
    return (
        page.get("ocr_status") in {"failed", "unusable", "skipped_budget"}
        or bool(page.get("ocr_failure"))
        or (is_ocr_text(page) and (page.get("ocr_confidence") or 0) < 80)
    )


class PassageMatcher:
    def __init__(self, query, mode):
        self.query = query.strip()
        self.literal = re.compile(re.escape(self.query), re.IGNORECASE)
        self.mode = mode
        if mode not in {"exact", "approximate"}:
            raise DomainError("needs_input", "Choose exact or approximate search.")
        if mode == "approximate" and not re.fullmatch("[a-zA-Z]{7,32}", self.query):
            raise DomainError(
                "needs_input",
                "Approximate OCR search requires one English word of 7 to 32 letters.",
            )
        self.folded = self.query.lower()

    def find(self, page):
        text = page["text"]
        literal = self.literal.search(text)
        if literal:
            return literal.start(), literal.end(), "exact", 1.0
        if self.mode != "approximate" or not is_ocr_text(page):
            return None
        previous = None
        best = None
        size = len(self.folded)
        for word in _WORD.finditer(text):
            starts = [word.start()]
            if (
                previous
                and word.start() - previous.end() <= 4
                and re.fullmatch(r"[ \t]{1,4}", text[previous.end() : word.start()])
            ):
                starts.append(previous.start())
            previous = word
            for start in starts:
                if not size <= word.end() - start <= size + 4:
                    continue
                candidate = "".join(text[start : word.end()].lower().split())
                if len(candidate) != size:
                    continue
                changes = [(a, b) for a, b in zip(candidate, self.folded, strict=True) if a != b]
                if len(changes) > min(2, size // 5) or not all(
                    any(a in group and b in group for group in _CONFUSIONS) for a, b in changes
                ):
                    continue
                score = round(1 - len(changes) / size, 4)
                if best is None or score > best[3]:
                    best = start, word.end(), "approximate", score
        return best


def match_fields(row, page, match):
    start, end, kind, similarity = match
    return {
        "state": page.get("state"),
        "ocr_status": page.get("ocr_status"),
        "match_type": kind,
        "matched_text": page["text"][start:end],
        "similarity": similarity,
        "visually_verified": False,
        "parser": row.file_state.get("parser"),
        "source_version": row.file_state.get("version"),
    }
