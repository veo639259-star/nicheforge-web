"""Seed the Idea Bank with sample PENDING ideas. Skips entirely if the
ideas table is non-empty. Run: python seed_sample.py"""
import os

import db as idea_db

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "nicheforge.db")

SAMPLES = [
    ("wicketverse",
     "Pak vs India T20: last 5 overs thriller recap",
     "Short video script breaking down the final overs — key wickets, DRS drama, crowd reactions."),
    ("wicketverse",
     "Babar Azam cover drive masterclass reel",
     "9:16 compilation idea: 6 of his best cover drives this season with commentary-style caption."),
    ("pakwire",
     "Lahore metro expansion announced — routes & timeline",
     "Card post: proposed new routes, phase timeline, and what it means for commuters."),
    ("pakwire",
     "Monsoon alert: heavy rain expected in Punjab this weekend",
     "Urgent news card with PDMA guidance and affected districts."),
    ("memeistan",
     "Load-shedding vs inverter owners — desi meme",
     "Image macro: 'Woh log jinke paas inverter hai' flexing during a 4-hour cut."),
    ("memeistan",
     "Ammi: 'beta rishta aa gaya' — exam week version",
     "Relatable Roman Urdu meme for students in supply exams."),
    ("maloomat",
     "World's shortest war lasted 38 minutes",
     "Anglo-Zanzibar War fact card with date and reference."),
    ("deen",
     "Hadith: actions are judged by intentions (Bukhari)",
     "Urdu translation card with Arabic-free layout, reference only."),
]


def main():
    idea_db.init_db(DB_PATH)
    if idea_db.list_ideas(DB_PATH):
        print("ideas table already has rows — skipping seed.")
        return
    added = 0
    for niche, title, detail in SAMPLES:
        ok, info = idea_db.add_idea(DB_PATH, niche, title, detail)
        if ok:
            added += 1
            print("+", info)
        else:
            print("x", info)
    print("seeded {} sample ideas".format(added))


if __name__ == "__main__":
    main()
