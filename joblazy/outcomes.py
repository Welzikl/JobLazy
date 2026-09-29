"""Explicit application receipts; errors and ambiguous acknowledgements are not success."""
import re
from urllib.parse import urlsplit

SELECTOR='[role="status"], [role="alert"], .application-confirmation, [data-testid="application-success"]'
NEGATIVE=re.compile(r"\b(?:not|unable|failed|failure|error|unsuccessful|pending|incomplete|cannot|couldn't|can't|hasn't|haven't)\b",re.I)
POSITIVE=re.compile(
    r"^(?:(?:your |the )?application (?:has been |was )?(?:successfully )?(?:received|submitted)(?: successfully)?"
    r"|we(?:'ve| have)? (?:successfully )?received your application"
    r"|thank(?:s| you) for (?:applying(?: to [^.!?]+)?|(?:submitting )?your application))[.!]?$",re.I)


def receipt_messages(texts):
    if any(NEGATIVE.search(text) for text in texts):return []
    messages=[]
    for text in texts:
        for sentence in re.split(r'(?<=[.!?;,])\s+|\s+[—–-]\s+|\n+',text):
            sentence=' '.join(sentence.split()).rstrip(',;')
            if POSITIVE.fullmatch(sentence):
                normalized=sentence.rstrip('.!').casefold()
                if normalized not in messages:messages.append(normalized)
    return messages


def origin(url):
    value=urlsplit(url)
    return (value.scheme,value.netloc)


def observe_receipt(frame,expected_origin):
    if frame.is_detached():return {'confirmed':[],'reason':'Application frame detached'}
    if origin(frame.url)!=expected_origin:
        return {'confirmed':[],'reason':'Application frame left its original origin','frame_url':frame.url}
    texts=[loc.inner_text().strip() for loc in frame.locator(SELECTOR).all() if loc.is_visible()]
    return {'confirmed':receipt_messages(texts),'observed':texts,'frame_url':frame.url}
