# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest
from tokenizers import Tokenizer as HFTokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from ragdbman.chunking import Tokenizer, chunk_document, tokenizer_path
from ragdbman.errors import RagError
from ragdbman.extract.text import markdown, source_code
from ragdbman.metadata import candidate_terms, extract_facts
from ragdbman.models import Block, Document


@pytest.fixture
def tok():
    return Tokenizer(allow_approximate=True)


def test_exact_and_approximate(tmp_path):
    path = tmp_path / "tokenizer.json"
    hf = HFTokenizer(WordLevel({"[UNK]": 0, "hello": 1, "world": 2}, unk_token="[UNK]"))
    hf.pre_tokenizer = Whitespace()
    hf.save(str(path))
    exact = Tokenizer(path)
    assert exact.mode == "exact"
    assert exact.count("hello world") == 2
    assert exact.boundaries("hello world") == [(0, 5), (6, 11)]
    approx = Tokenizer(allow_approximate=True)
    assert approx.boundaries("ábcdef")[-1][1] == 6
    assert approx.count("") == 0
    with pytest.raises(RagError):
        Tokenizer(tmp_path / "missing.json")
    path.write_text("broken")
    with pytest.raises(RagError):
        Tokenizer(path)


@pytest.mark.parametrize("model", ["../escape", "/abs", "x/../y", r"..\bad"])
def test_unsafe_tokenizer_model(model, tmp_path):
    with pytest.raises(RagError):
        tokenizer_path(tmp_path, model)


def test_namespaced_tokenizer_path(tmp_path):
    assert tokenizer_path(tmp_path, "org/model:f16") == tmp_path / "tokenizer" / "org" / "model:f16.json"


def test_heading_boundaries(tok):
    doc = markdown("# One\n\nFirst text.\n\n## Two\n\nSecond text.\n\n# Three\n\nThird.")
    chunks = chunk_document(doc, tok, 500, 20)
    assert len(chunks) == 3
    assert chunks[1].section_path == "One > Two"
    assert all(not ("First text" in c.text and "Second text" in c.text) for c in chunks)
    assert chunks[0].percent_position == 0
    assert chunks[2].percent_position > chunks[1].percent_position


def test_same_section_packs(tok):
    doc = markdown("# A\n\nPara one.\n\nPara two.")
    chunks = chunk_document(doc, tok, 100, 0)
    assert len(chunks) == 1
    assert "Para one" in chunks[0].text and "Para two" in chunks[0].text


def test_empty_document(tok):
    assert chunk_document(Document([], "text"), tok, 20, 0) == []


@pytest.mark.parametrize("size,overlap", [(0, 0), (10, 10), (10, -1)])
def test_invalid_budgets(tok, size, overlap):
    with pytest.raises(RagError):
        chunk_document(Document([], "text"), tok, size, overlap)


def test_long_sentence_windows_and_unicode_offsets(tok):
    doc = Document([Block("Árvíztűrő tükörfúrógép " * 100)], "text")
    chunks = chunk_document(doc, tok, 40, 8)
    assert len(chunks) > 2
    for c in chunks:
        assert c.text == doc.full_text[c.char_start : c.char_end]
        assert c.token_count <= 40
    assert chunks[-1].char_end == len(doc.full_text)


def test_code_never_splits_lines(tok):
    content = "def hello():\n" + "    " + "x" * 500 + "\n    return 1\n\ndef other():\n    pass\n"
    doc = source_code(content, Path("a.py"))
    chunks = chunk_document(doc, tok, 20, 4)
    assert any("x" * 500 in c.text for c in chunks)
    assert any(c.line_start == 2 and c.line_end == 2 for c in chunks)
    for c in chunks:
        assert c.line_start and c.line_end
        assert c.text == doc.full_text[c.char_start : c.char_end]


def test_overlap_and_no_infinite_loop(tok):
    doc = Document([Block(f"{i:08d}", section_path="same") for i in range(20)], "text")
    chunks = chunk_document(doc, tok, 10, 6)
    assert 1 < len(chunks) < 25
    assert chunks[1].char_start < chunks[0].char_end
    assert chunks[-1].char_end == len(doc.full_text)


def test_atomic_and_location_metadata(tok):
    doc = Document([Block("very long " * 80, atomic=True, page=7, time_start_ms=0, time_end_ms=1000)], "pdf")
    chunks = chunk_document(doc, tok, 10, 2)
    assert len(chunks) == 1
    assert chunks[0].page_start == 7
    assert chunks[0].time_end_ms == 1000


@pytest.mark.parametrize(
    "text,field,value",
    [
        ("Price: €1,299", "price", 1299),
        ("cost $2.50", "price", 2.5),
        ("Amount: 12 USD", "amount", 12),
        ("total £100", "total", 100),
        ("discount 15%", "discount_percent", 15),
        ("tax 20%", "tax_percent", 20),
        ("rating 4.6", "rating", 4.6),
        ("score 92.5", "score", 92.5),
        ("Rank #7", "rank", 7),
        ("count 12", "count", 12),
        ("quantity 6", "quantity", 6),
        ("weight 5kg", "weight", 5),
        ("length 15cm", "length", 15),
        ("version v2.1", "version", 2.1),
    ],
)
def test_labeled_facts(text, field, value):
    fact = next(f for f in extract_facts(text) if f["field"] == field)
    assert fact["normalized_number"] == value
    assert text[fact["char_start"] : fact["char_end"]].strip() == fact["raw_value"]


def test_locale_and_currency():
    fact = extract_facts("Price €1.299,50", "de")[0]
    assert fact["normalized_number"] == 1299.5
    assert fact["currency_code"] == "EUR"


@pytest.mark.parametrize(
    "text,field",
    [
        ("Published 2026-08-22", "published_date"),
        ("Event date: 2026/08/22", "event_date"),
        ("Created 22 August 2026", "created_date"),
        ("Updated August 22, 2026", "updated_date"),
        ("On August 22 2026", "date"),
    ],
)
def test_dates(text, field):
    fact = extract_facts(text)[0]
    assert fact["field"] == field
    assert fact["normalized_date_utc"] == "2026-08-22T00:00:00Z"


def test_unicode_and_no_hallucinated_facts():
    assert extract_facts("The building has 12 floors, he’s unsure.") == []
    assert (
        extract_facts("x" * 10 + "he’s redefined this. Published 2026-08-22")[0]["field"] == "published_date"
    )
    assert extract_facts("2026-02-31") == []
    assert extract_facts("version 1.2.3") == []


def test_keyword_uniqueness():
    terms = candidate_terms("The Embedding Retrieval System and the Retrieval Pipeline")
    assert terms.count("retrieval") == 1
    assert "the" not in terms and "embedding" in terms
