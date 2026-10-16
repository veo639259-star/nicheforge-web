"""NicheForge Phase 3 — Comment Mining.

Reads comments on a post (via a duck-typed driver) and turns audience
questions + frequent requests into new idea seeds in the approval inbox.

Pipeline:
  1. driver.get_comments(url) -> list of comment strings.
  2. Questions = comments ending with "?".
  3. Frequent requests = simple word frequency over non-stopword tokens
     (English + Roman Urdu stopwords), turned into question-like seeds.
  4. Top 10 seeds -> db.add_idea(niche, title=seed, detail="source: "+url).

db is imported lazily inside mine_comments() to avoid circular imports
(browser_track.comments -> nicheforge.db).

DRY-RUN is the default: pass a mock driver and nothing touches the
network; the seeds still land in the (temp/test) idea bank.
"""

import re
from collections import Counter

STOPWORDS = frozenset("""
a an the and or but if then else for of on in to at from by with as is are
was were be been being has have had do does did will would can could should
shall may might must not no yes so such very too also just only more most
other some any all each both few many much own same than then there their
they them he she it we you i me my our your his her its him us this that
these those what when where who whom whose which why how
aur or ka ki ke ko se ne mein main par bhi hai hain tha thi the hoga
nahi nahi nahi kyun kya kab kahan kaise kon kis ke liye
""".split()) | frozenset(["nahin"])

WORD_RE = re.compile(r"[A-Za-z]{3,}")
MAX_SEEDS = 10


def _load_db():
    """Lazy db import — matches the nicheforge test convention
    (sys.path includes the nicheforge root, `import db`)."""
    try:
        import db  # noqa: F401
        return db
    except ImportError:
        from nicheforge import db  # noqa: F401
def _extract_questions(comments):
    seen = set()
    questions = []
    for c in comments:
        c = (c or "").strip()
        if c.endswith("?") and c not in seen and len(c) > 8:
            seen.add(c)
            questions.append(c)
    return questions


def _request_seeds(comments, already):
    """Top non-stopword tokens -> question-like seeds, excluding seeds
    we already have."""
    counter = Counter()
    for c in comments:
        for tok in WORD_RE.findall((c or "").lower()):
            if tok not in STOPWORDS:
                counter[tok] += 1
    seeds = []
    for word, count in counter.most_common():
        if count < 2:  # need at least some repetition to call it "frequent"
            break
        seed = 'Fan request: more on "%s"?' % word
        if seed not in already:
            seeds.append(seed)
            already.add(seed)
    return seeds


def mine_comments(db_path, driver, post_url, niche, dry_run=True):
    """Mine comments into idea seeds. Returns list of (ok, info)."""
    db = _load_db()

    comments = driver.get_comments(post_url) or []
    comments = [c for c in comments if isinstance(c, str) and c.strip()]

    questions = _extract_questions(comments)
    used = set(questions)
    seeds = questions[:MAX_SEEDS]
    if len(seeds) < MAX_SEEDS:
        seeds += _request_seeds(comments, used)[: MAX_SEEDS - len(seeds)]
    seeds = seeds[:MAX_SEEDS]

    results = []
    for seed in seeds:
        ok, info = db.add_idea(db_path, niche, title=seed,
                               detail="source: " + post_url)
        results.append((ok, info))
    return results
