#!/usr/bin/env python3
"""NicheForge Phase 3 — browser_track tests (image queue, paste points,
harvest, comment mining, asset organizer). Plain asserts, temp DB/dir."""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

ROOT = "/home/hatch/workspace/nicheforge"
sys.path.insert(0, ROOT)

from browser_track import images, paste_points, harvest, comments  # noqa: E402

tmp = tempfile.mkdtemp(prefix="nf-bt-")
db_path = os.path.join(tmp, "bt.db")
assets_root = os.path.join(tmp, "ws")
out_dir = os.path.join(tmp, "prompts")

passed = [0]


def check(name, cond):
    assert cond, "FAILED: %s" % name
    passed[0] += 1
    print("ok - %s" % name)


# ---------------------------------------------------------------- images
def make_prompt(idea_id, text):
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, "prompt_%s.json" % idea_id)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"niche": "lafz", "idea_id": idea_id,
                   "prompt_text": text}, fh)
    return p


p1 = make_prompt("idea1", "A golden quote card " * 40)
p2 = make_prompt("idea2", "A green quote card " * 40)

ids = images.queue_from_prompts(db_path, "lafz", [p1, p2])
check("queue_from_prompts returns 2 ids", len(ids) == 2 and ids[0] != ids[1])

conn = sqlite3.connect(db_path)
rows = conn.execute("SELECT status FROM image_jobs").fetchall()
conn.close()
check("jobs start queued", all(r[0] == "queued" for r in rows))

driver = images.MockDriver()
runner = images.ImageJobRunner(db_path, driver, dry_run=True,
                               assets_root=assets_root)
results = [runner.run_job(i) for i in ids]
check("both jobs ok", all(r[0] for r in results))

conn = sqlite3.connect(db_path)
statuses = [r[0] for r in conn.execute(
    "SELECT status FROM image_jobs ORDER BY id").fetchall()]
conn.close()
check("both jobs done", statuses == ["done", "done"])

today = None
niches_assets = os.path.join(assets_root, "niches", "lafz", "assets")
days = os.listdir(niches_assets)
check("dated assets dir created", len(days) == 1)
today = days[0]
day_dir = os.path.join(niches_assets, today)
files = os.listdir(day_dir)
pngs = sorted(f for f in files if f.endswith(".png"))
check("8 pngs downloaded", len(pngs) == 8)
check("img_<jobid>_<n> naming",
      pngs[0] == "img_%d_0.png" % ids[0] and pngs[4] == "img_%d_0.png" % ids[1])
check("2 manifests exist",
      all(os.path.exists(os.path.join(day_dir, "manifest_%d.json" % i))
          for i in ids))
with open(os.path.join(day_dir, "manifest_%d.json" % ids[0])) as fh:
    m = json.load(fh)
check("manifest has prompt_text<=500 + source + job_id",
      len(m["prompt_text"]) <= 500 and m["source"] == "mock"
      and m["job_id"] == ids[0])

# MockDriver recorded the flow, no network involved
kinds = [k for k, _ in driver.log]
check("driver flow goto->submit->wait->4 downloads",
      kinds == ["goto", "submit_prompt", "wait_for_images"] +
      ["download_image"] * 4 + ["goto", "submit_prompt", "wait_for_images"] +
      ["download_image"] * 4)

# guard hook stops a run
def noisy_guard(text):
    return "captcha wall" if "submitted" in text else None

p3 = make_prompt("idea3", "Blocked prompt " * 40)
[gid] = images.queue_from_prompts(db_path, "lafz", [p3])
r2 = images.ImageJobRunner(db_path, images.MockDriver(),
                           dry_run=True, assets_root=assets_root,
                           guards=[noisy_guard])
ok, info = r2.run_job(gid)
check("guard signal fails job, never hammers", not ok and "captcha" in info)
conn = sqlite3.connect(db_path)
st = conn.execute("SELECT status, error FROM image_jobs WHERE id = ?",
                  (gid,)).fetchone()
conn.close()
check("failed status + error recorded",
      st[0] == "failed" and "captcha" in (st[1] or ""))

# contact sheet
sheet = images.build_contact_sheet(db_path, "lafz", today, root=assets_root)
check("contact sheet html exists", os.path.exists(sheet))
with open(sheet, encoding="utf-8") as fh:
    html = fh.read()
check("sheet references images + Pick buttons",
      pngs[0] in html and "Pick</button>" in html
      and html.count('class="shot') == 8)

pick_path = os.path.join(day_dir, pngs[0])
pid = images.record_pick(db_path, "lafz", today, pick_path)
check("record_pick returns id", isinstance(pid, int) and pid > 0)
conn = sqlite3.connect(db_path)
n = conn.execute("SELECT COUNT(*) FROM image_picks").fetchone()[0]
conn.close()
check("pick persisted", n == 1)

# re-run of a done job is refused
ok, info = runner.run_job(ids[0])
check("done job not re-run", not ok and "not queued" in info)

# ---------------------------------------------------------- paste points
a = paste_points.request(db_path, "Flow paste", "https://labs.google/flow",
                         "paste the 9:16 prompt")
b = paste_points.request(db_path, "Vids paste", "https://labs.google/vids")
check("request returns ids", a != b and a > 0)

nxt = paste_points.next_pending(db_path)
check("next_pending returns oldest", nxt["id"] == a
      and nxt["label"] == "Flow paste" and nxt["url"] == "https://labs.google/flow")
check("pending_count 2", paste_points.pending_count(db_path) == 2)
check("list_pending oldest first",
      [p["id"] for p in paste_points.list_pending(db_path)] == [a, b])

paste_points.complete(db_path, a)
nxt = paste_points.next_pending(db_path)
check("complete -> next is second", nxt is not None and nxt["id"] == b)
paste_points.skip(db_path, b)
check("skip -> pending_count 0", paste_points.pending_count(db_path) == 0)
check("next_pending None when empty", paste_points.next_pending(db_path) is None)

# ---------------------------------------------------------------- harvest
class MockHarvestDriver:
    def __init__(self, posts):
        self.posts = posts
        self.visited = []
        self.slept = []

    def goto(self, url):
        self.visited.append(url)

    def extract_posts(self):
        return list(self.posts)


t1 = harvest.add_target(db_path, "memeistan", "https://fb.com/page1", "Page 1")
t2 = harvest.add_target(db_path, "memeistan", "https://fb.com/page2", "Page 2")
tgts = harvest.list_targets(db_path, "memeistan")
check("2 targets listed", len(tgts) == 2 and tgts[0]["id"] == t1)
check("list_targets all-niches filter",
      len(harvest.list_targets(db_path, "deen")) == 0
      and len(harvest.list_targets(db_path)) == 2)

hdrv = MockHarvestDriver([
    {"snippet": "funny cat reel", "likes": 120, "comments_count": 5,
     "posted_at_text": "2h"},
    {"snippet": "desi meme", "likes": 340, "comments_count": 12,
     "posted_at_text": "5h"},
])
res = harvest.run_harvest(db_path, hdrv, niche="memeistan", dry_run=True,
                          min_gap_secs=0)
check("harvest visits both targets", res["visited"] == 2
      and not res["stopped"])
check("sequential goto order", hdrv.visited == ["https://fb.com/page1",
                                                "https://fb.com/page2"])
conn = sqlite3.connect(db_path)
n = conn.execute("SELECT COUNT(*) FROM harvest_posts").fetchone()[0]
snip = conn.execute("SELECT snippet, likes FROM harvest_posts"
                    " ORDER BY id").fetchall()
conn.close()
check("4 post rows stored", n == 4)
check("post fields stored", snip[0][0] == "funny cat reel" and snip[0][1] == 120)

# signal hook stops mid-run
def stop_guard(post):
    return "login wall" if "desi" in post.get("snippet", "") else None

hdrv2 = MockHarvestDriver([
    {"snippet": "ok post", "likes": 1, "comments_count": 0,
     "posted_at_text": "1h"},
    {"snippet": "desi trap post", "likes": 2, "comments_count": 0,
     "posted_at_text": "2h"},
    {"snippet": "never reached", "likes": 3, "comments_count": 0,
     "posted_at_text": "3h"},
])
conn = sqlite3.connect(db_path)
before = conn.execute("SELECT COUNT(*) FROM harvest_posts").fetchone()[0]
conn.close()
res2 = harvest.run_harvest(db_path, hdrv2, niche="memeistan", dry_run=True,
                           min_gap_secs=0, guards=[stop_guard])
conn = sqlite3.connect(db_path)
after = conn.execute("SELECT COUNT(*) FROM harvest_posts").fetchone()[0]
conn.close()
check("guard stops run immediately",
      res2["stopped"] and "login wall" in res2["reason"]
      and after == before + 1)

# --------------------------------------------------------------- comments
class MockCommentDriver:
    def get_comments(self, url):
        return [
            "Bhai ye kab hoga? Bohot wait kar rahe hain sab log idhar",
            "next part kab aayega?",
            "mujhe ye wala pasand aaya, aur bhi chahiye please",
            "part 2 kab aayega dosto? sab pooch rahe hain",
            "bohot ala, aur bhi banao",
            "yeh kahan ki video hai?",
            "nice",
            "aur bhi chahiye aisi videos",
            "part 2 kab aayega dosto, batao na?",
        ]


cresults = comments.mine_comments(db_path, MockCommentDriver(),
                                  "https://fb.com/post/123", "paheli")
check("mine_comments returns (ok, info) tuples",
      len(cresults) > 0 and all(len(r) == 2 for r in cresults))
# dedup may legitimately reject near-identical seeds — questions must land
check("question seeds inserted",
      sum(1 for ok, _ in cresults if ok) >= 3)

conn = sqlite3.connect(db_path)
ideas = conn.execute(
    "SELECT title, detail FROM ideas WHERE niche = 'paheli'"
    " ORDER BY id").fetchall()
conn.close()
check("question seeds became ideas",
      any("kab aayega" in t for t, _ in ideas))
check("ideas carry source link",
      all("https://fb.com/post/123" in d for _, d in ideas))
check("max 10 seeds", len(ideas) <= 10)

# ---------------------------------------------------------- asset organizer
stray = os.path.join(day_dir, "img_999_0.png")
with open(stray, "wb") as fh:
    fh.write(images.MockDriver()._pngs[0])
strays = images.verify_no_strays("lafz", root=assets_root)
check("verify_no_strays finds planted stray", stray in strays)

created = images.organize_assets("lafz", root=assets_root)
check("organize_assets writes stub manifest",
      any("manifest_999.json" in c for c in created))
check("no strays after organize",
      images.verify_no_strays("lafz", root=assets_root) == [])

shutil.rmtree(tmp, ignore_errors=True)
print("\nALL %d TESTS PASSED" % passed[0])
