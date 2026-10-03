"""Mask the identifiers a photographed document should never carry any further.

A bank letter, a pension slip or an Aadhaar card holds numbers that must not reach a model
prompt, a log line, DynamoDB, the family dashboard or Polly's audio. This runs inside the
OCR step, before the text goes anywhere else, so every downstream component only ever sees
the masked form. Nothing in Raksha needs a full account number: no tool takes one.

Deliberately blunt, and deliberately narrow:
- masked: 11-18 contiguous digits (bank account, Aadhaar), and 4-4-4(-4) grouped digits
  (the way Aadhaar and card numbers are printed)
- left alone: amounts, dates, pincodes and 10-digit phone numbers, which the planner needs
  in order to be useful

The last 4 digits survive, because that is how a bank tells an elder which account it means.
"""
import re

# 11+ contiguous digits: account numbers, Aadhaar written without spaces
CONTIGUOUS = re.compile(r"\b\d{11,18}\b")
# 4-4-4 or 4-4-4-4 groups: how Aadhaar and card numbers are actually printed
GROUPED = re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}(?:[ -]\d{4})?\b")

MASK_CHAR = "X"


def _mask(match):
    digits = re.sub(r"\D", "", match.group(0))
    return MASK_CHAR * (len(digits) - 4) + digits[-4:]


def redact(text):
    """Return the text with long identifier numbers masked to their last 4 digits."""
    if not text:
        return text
    return CONTIGUOUS.sub(_mask, GROUPED.sub(_mask, text))


def redact_pairs(pairs):
    """Same, for the key/value pairs Textract's FORMS analysis returns."""
    return {redact(key): redact(value) for key, value in (pairs or {}).items()}
