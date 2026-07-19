# Content provenance and retrieved-text handling

This document is the written answer to the security-questionnaire line that asks
"how do you sanitize retrieved content before passing it to an AI model?" It
records what the USPTO Patent File Wrapper (PFW) MCP does, what it deliberately
does not do, and why. (Implementation cross-reference: the runtime scanner and
labeling constant live in `src/patent_filewrapper_mcp/shared/injection_scan.py`;
the server-instructions posture paragraph is in
`src/patent_filewrapper_mcp/main.py` `SERVER_INSTRUCTIONS`.)

## Source corpus

Every document served by this system originates from USPTO Open Data Portal
APIs at `api.uspto.gov`: the Patent File Wrapper API (prosecution documents and
metadata), the Office Action text and rejections APIs, and USPTO-published
patent/application XML. Filers are identified applicants and practitioners, and
prosecution documents are filed under the USPTO's duty of candor and signature
rules and carry legal effect. This is a curated regulatory corpus, not the open
web: there is no anonymous user-generated content in the retrieval path. That
said, "curated" is not "trusted" — a file wrapper can embed arbitrary
applicant- and third-party-drafted content (attachments, declarations, cited
references, IDS submissions), which is the realistic injection surface.

## What we deliberately do NOT do: strip or rewrite document text

Patent prosecution research depends on verbatim fidelity. A "sanitization" pass
that removes or rewrites token sequences from an office action, claim set, or
specification would corrupt the exact language attorneys are retrieving —
examiner reasoning, claim wording, applicant arguments. Document text is
therefore served verbatim (or as faithful OCR of image-filed documents via
PyPDF2, Mistral OCR, or Docling — extraction, not rewriting), with provenance
attached, and is never mutated in the name of injection defense.

## What we do instead: structured, provenance-aware interfaces

1. **Data/instruction separation by labeling.** Every tool that returns
   retrieved file-wrapper text (`pfw_get_document_content_with_ocr`,
   `get_oa_text`, `get_patent_or_application_xml`) carries a machine-readable
   `provenance_note` stating that the text is quoted data, not instructions,
   and the server-level instructions direct the consuming model to report
   instruction-like language found inside retrieved text rather than act on
   it, and to present applicant- or examiner-drafted characterizations as
   attributed positions, not established fact.
2. **Detection-only injection annotation.** Retrieved text is additionally run
   through a runtime scanner (`shared/injection_scan.py`) for
   instruction-override, prompt-extraction, and encoding-evasion language and
   suspicious densities of invisible Unicode. On a hit the response gains an
   `injection_scan` annotation naming the flagged document and the kinds of
   pattern found — never the matched text — so nothing sensitive can flow
   into logs or transcripts. The annotation is absent entirely when content is
   clean, and the text itself is always returned untouched.
3. **No generative step in the retrieval path.** The server performs search,
   field projection, and text extraction (PyPDF2 parsing, Mistral OCR, Docling
   OCR — faithful transcription of image-filed documents). No language model
   summarizes, rewrites, or ranks retrieved content inside this server;
   interpretation happens in the consuming assistant, where the labeling above
   applies.
4. **Content-minimizing logging.** Logs record operational flow metadata only —
   tool, request ID, status, counts, public identifiers — never query text,
   request/response bodies, or OCR/document content. The sink-level
   `SanitizingFilter` (`shared/log_sanitizer.py`), attached to every log
   handler by `config/log_config.py` `setup_logging()`, is the guarantee;
   scanner output is restricted to kind labels and document identifiers by
   design, so it is safe to relay and log.
5. **Codebase hygiene is a separate, complementary layer.** The repository
   also ships a commit-time prompt-injection scanner (`.security/`, wired via
   pre-commit) that guards the project's own source tree against
   injection-shaped strings. It scans the codebase at commit time; the runtime
   scanner above annotates retrieved USPTO corpus content at tool-call time.
   The two layers share a pattern taxonomy but are independent controls.

## Residual-risk statement

Prompt-injection risk in this product reduces to: a prosecution document (or
material embedded in one) contains text crafted to influence a downstream AI
assistant. The controls above ensure such text (a) reaches the assistant
clearly labeled as quoted document content with a provenance note, (b) is
flagged with a detection-only `injection_scan` annotation when it is
injection-shaped, and (c) cannot leak through the logging pipeline, which
records flow metadata only. We consider stripping-based defenses inappropriate
for a corpus whose value is verbatim prosecution text, and
labeling-plus-detection the correct control for this threat model.
