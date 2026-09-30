# =====================================
# CONVERSATION vs. DOCUMENT EVIDENCE
# =====================================
# Earlier assistant replies (and summaries of them) can contain
# mistakes or general-knowledge claims. If they were treated as facts
# about the uploaded PDF, one unsupported answer would keep coming back
# as "the PDF says ..." on later turns. Every agent that sees both the
# conversation and retrieved PDF text includes this rule, and the two
# are always shown under clearly separate headings.

CONVERSATION_SECTION_NOTE = (
    "(conversation only — NOT evidence of what the document says)"
)

EVIDENCE_SECTION_TITLE = (
    "RETRIEVED DOCUMENT EVIDENCE "
    "(the ONLY authority on what the PDF says)"
)

GROUNDING_RULE = """
EVIDENCE RULE:
- Only the RETRIEVED DOCUMENT EVIDENCE section shows what the PDF says.
- The conversation summary and history — including your own earlier
  replies — are NOT evidence about the PDF. Earlier replies may be wrong
  or may have come from general knowledge.
- Use the conversation only to understand what the student is referring
  to. Never present a fact as coming from the PDF unless it appears in
  the RETRIEVED DOCUMENT EVIDENCE for this turn.
- If an earlier reply conflicts with the evidence, the evidence wins;
  say so briefly.
"""
