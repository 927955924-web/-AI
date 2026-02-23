# -*- coding: utf-8 -*-
"""
Core utilities and helpers for the application.
"""
import uuid
import hashlib
import re


def generate_id(prefix: str) -> str:
    """Generate a prefixed UUID."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def md5_hash(text: str) -> str:
    """Generate MD5 hash of text."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def clean_text(text: str) -> str:
    """Clean text by removing extra whitespace and punctuation."""
    if not text:
        return ""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text.strip())
    # Remove common punctuation for matching
    text = re.sub(r'[,.!?;:\'\"()\[\]{}]', '', text)
    return text
