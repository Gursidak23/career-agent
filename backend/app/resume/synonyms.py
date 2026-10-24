"""Synonym / abbreviation map for ATS keyword matching.

Maps a canonical skill to common aliases/abbreviations so that, e.g., a resume
saying "JS" or "ReactJS" still matches a JD asking for "JavaScript" / "React".
"""

from __future__ import annotations

# canonical (lowercase) -> aliases (lowercase)
_SYNONYMS: dict[str, list[str]] = {
    "javascript": ["js", "ecmascript", "es6", "vanilla js"],
    "typescript": ["ts"],
    "python": ["py"],
    "machine learning": ["ml"],
    "deep learning": ["dl"],
    "natural language processing": ["nlp"],
    "large language models": ["llm", "llms", "large language model"],
    "kubernetes": ["k8s"],
    "amazon web services": ["aws"],
    "google cloud platform": ["gcp", "google cloud"],
    "microsoft azure": ["azure"],
    "continuous integration": ["ci", "ci/cd", "cicd"],
    "continuous deployment": ["cd", "ci/cd", "cicd"],
    "postgresql": ["postgres", "psql"],
    "react": ["reactjs", "react.js"],
    "node.js": ["node", "nodejs"],
    "next.js": ["nextjs", "next"],
    "vue": ["vuejs", "vue.js"],
    "rest api": ["rest", "restful", "restful api"],
    "object-oriented programming": ["oop", "object oriented"],
    "infrastructure as code": ["iac"],
    "site reliability engineering": ["sre"],
    "tensorflow": ["tf"],
    "pytorch": ["torch"],
    "scikit-learn": ["sklearn", "scikit learn"],
    "hugging face": ["huggingface", "hf"],
    "vector database": ["vector db", "vectordb", "vector store"],
    "retrieval augmented generation": ["rag"],
    "a/b testing": ["ab testing", "split testing"],
    "user experience": ["ux"],
    "user interface": ["ui"],
}

# Build a fast lookup: every term -> the full set of its equivalents.
_EQUIVALENTS: dict[str, set[str]] = {}
for _canon, _aliases in _SYNONYMS.items():
    _group = {_canon, *_aliases}
    for _term in _group:
        _EQUIVALENTS.setdefault(_term, set()).update(_group)


def variants_of(keyword: str) -> set[str]:
    """All equivalent surface forms of a keyword (including itself)."""
    kw = keyword.strip().lower()
    return _EQUIVALENTS.get(kw, {kw})
