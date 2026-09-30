import io
import json
import zipfile

import pytest

from app.core.chunking import MAX_CHARS, chunk_text
from app.core.extraction import ExtractionError, clean_markdown, extract_file


def test_obsidian_syntax_is_cleaned():
    note = "---\ntags: [research]\n---\n# Churn\nSee [[Accounts/Acme Corp|Acme]] and [[Globex]].\n![[diagram.png]]\n%% private %%\nDone."
    text = clean_markdown(note)
    assert "tags:" not in text
    assert "See Acme and Globex." in text
    assert "diagram.png" not in text and "private" not in text


def test_bullets_and_speaker_turns_become_separate_passages():
    text = (
        "## Pain points\n"
        "- Export stops at 1,000 rows, so finance stitches files together.\n"
        "- SSO logs everyone out every 30 minutes.\n\n"
        "## Call\n"
        "**Priya:** The CSV download is incomplete for big reports.\n"
        "Sam (00:12): Is that every export or only large ones?\n"
        "Priya: Only the large ones.\n"
    )
    chunks = chunk_text(text)
    assert [c.text for c in chunks][:2] == [
        "Export stops at 1,000 rows, so finance stitches files together.",
        "SSO logs everyone out every 30 minutes.",
    ]
    assert chunks[0].section == "Pain points"
    assert chunks[2].speaker == "Priya" and chunks[2].text.startswith("Priya: The CSV")
    assert chunks[3].speaker == "Sam"
    # A turn shorter than the minimum is joined to the previous passage, not dropped
    assert chunks[-1].text.endswith("Priya: Only the large ones.") or chunks[-2].text.endswith("Priya: Only the large ones.")


def test_wrapped_pdf_lines_are_joined_but_slide_lines_are_split():
    wrapped = "Score 3. I get logged out constantly. Every half hour I have to go\nthrough Okta again and I've lost work twice."
    assert len(chunk_text(wrapped)) == 1
    slide = "SSO sessions expire every 30 minutes.\nInvoices are issued in USD without a VAT number.\nDashboards take a minute to load."
    assert len(chunk_text(slide)) == 3


def test_long_paragraphs_are_split_at_sentences():
    paragraph = " ".join(f"Sentence number {i} explains a different part of the onboarding problem." for i in range(40))
    chunks = chunk_text(paragraph)
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    assert all(c.text.endswith(".") for c in chunks)


def test_markdown_table_rows_become_labelled_passages():
    table = "| Customer | Issue |\n|---|---|\n| Acme | Export truncated at 1,000 rows |\n| Globex | SSO logout |"
    assert [c.text for c in chunk_text(table)] == ["Customer: Acme · Issue: Export truncated at 1,000 rows", "Customer: Globex · Issue: SSO logout"]


def test_csv_with_feedback_column_keeps_customer_and_arr():
    data = "Ticket,Customer,Plan,ARR,Message\n1,Acme,Enterprise,\"$120,000\",Export stops at 1000 rows\n2,Globex,growth,,SSO logs us out\n"
    [document], skipped = extract_file("tickets.csv", data.encode())
    assert document.kind == "table" and not skipped
    assert document.rows[0] == {"content": "Export stops at 1000 rows", "customer_id": "Acme", "customer_tier": "enterprise", "arr_value": 120000.0, "source_type": "spreadsheet_row"}
    assert document.rows[1]["arr_value"] is None


def test_csv_without_feedback_column_is_read_as_text():
    [document], _ = extract_file("usage.csv", b"account,seats\nAcme,120\nGlobex,40\n")
    assert document.kind == "document"
    assert "account: Acme · seats: 120" in document.text


def test_json_feedback_list():
    payload = json.dumps({"items": [{"comment": "Dark mode please", "account": "Acme", "mrr": 1000}]})
    [document], _ = extract_file("export.json", payload.encode())
    assert document.rows[0]["content"] == "Dark mode please"
    assert document.rows[0]["arr_value"] == 12000.0


def test_zip_vault_skips_hidden_folders_and_unsupported_files():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Vault/Notes/Churn.md", "# Churn\nAcme may leave over the export limit.")
        archive.writestr("Vault/.obsidian/app.json", "{}")
        archive.writestr("__MACOSX/Vault/._Churn.md", "junk")
        archive.writestr("Vault/attachments/diagram.png", "png")
    documents, skipped = extract_file("vault.zip", buffer.getvalue())
    assert [d.path for d in documents] == ["Vault/Notes/Churn.md"]
    assert documents[0].title == "Churn" and documents[0].kind == "note"
    assert skipped == [{"path": "Vault/attachments/diagram.png", "reason": ".png is not supported"}]


def test_unsupported_and_corrupt_files_raise_clear_errors():
    with pytest.raises(ExtractionError, match="not supported"):
        extract_file("photo.heic", b"...")
    with pytest.raises(ExtractionError, match="valid .zip"):
        extract_file("broken.zip", b"not a zip")
    with pytest.raises(ExtractionError, match="could not read"):
        extract_file("broken.docx", b"not a docx")


def test_small_project_with_several_topics_is_not_merged_into_one_theme():
    import numpy as np

    from app.core.clustering import cluster_feedback_embeddings

    rng = np.random.default_rng(0)
    dim = 384
    # Five problems about the same product: related directions, plus a few unrelated outliers
    domain = rng.normal(size=dim)
    domain /= np.linalg.norm(domain)
    topics = rng.normal(size=(5, dim))
    topics = 0.55 * topics / np.linalg.norm(topics, axis=1, keepdims=True) + 0.45 * domain
    vectors, labels = [], []
    for topic, count in enumerate([12, 10, 8, 7, 6]):
        centre = topics[topic] / np.linalg.norm(topics[topic])
        for _ in range(count):
            v = 0.7 * centre + 0.71 * rng.normal(size=dim) / np.sqrt(dim)
            vectors.append(v / np.linalg.norm(v))
            labels.append(topic)
    for _ in range(10):
        v = 0.4 * domain + rng.normal(size=dim) / np.sqrt(dim)
        vectors.append(v / np.linalg.norm(v))
        labels.append(-1)
    items = [{"id": i, "content": "", "clean_content": "", "embedding": v} for i, v in enumerate(vectors)]

    result = cluster_feedback_embeddings(items)
    assert result.total_dense_clusters == 5
