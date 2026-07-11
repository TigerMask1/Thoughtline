#!/usr/bin/env python3
"""
Daily content generator.

What it does, in order:
1. Loads topics/seed-niches.json (your list of niches) and topics/used.json (queue + history).
2. If the queue is low, asks Gemini to expand a niche into new long-tail topic ideas,
   filters out anything already used, and adds the rest to the queue.
3. Pops PAGES_PER_RUN topics off the queue, generates a full page for each via Gemini,
   writes it to _posts/, and marks the topic as used.

Run with: python scripts/generate.py
Requires env var GEMINI_API_KEY.
"""

import json
import os
import re
import sys
import time
import random
import datetime
import urllib.request

PAGES_PER_RUN = int(os.environ.get("PAGES_PER_RUN", "4"))
GEMINI_MODEL = "gemini-flash-latest"  # update if you want a specific pinned version
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USED_PATH = os.path.join(ROOT, "topics", "used.json")
SEED_PATH = os.path.join(ROOT, "topics", "seed-niches.json")
POSTS_DIR = os.path.join(ROOT, "_posts")

QUEUE_LOW_WATERMARK = 6
TOPICS_TO_GENERATE_PER_NICHE = 8


def call_gemini(prompt, temperature=0.9):
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature}
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        print("ERROR: unexpected Gemini response:", json.dumps(data)[:1000], file=sys.stderr)
        sys.exit(1)


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80]


def refill_queue_if_needed(state, seeds):
    if len(state["queue"]) >= QUEUE_LOW_WATERMARK:
        return state

    niches = seeds.get("niches", [])
    if not niches:
        print("No niches defined in topics/seed-niches.json - add some.", file=sys.stderr)
        return state

    niche = random.choice(niches)
    used_lower = {t.lower() for t in state["used_topics"]} | {t.lower() for t in state["queue"]}

    prompt = f"""You are helping plan content for a niche site about: "{niche['name']}"
Notes on scope: {niche.get('notes', 'none')}

Suggest {TOPICS_TO_GENERATE_PER_NICHE} specific, genuinely useful long-tail article topics for this niche.
Rules:
- Favor list, comparison, and compound/specific formats: "X ideas for [specific person/situation]",
  "X vs Y for [specific context]", "what to do when [specific situation]". These give a reason to
  click through and browse rather than getting fully answered in a single AI-generated snippet.
- Avoid single-fact phrasing that a search engine's AI answer box could fully resolve in one sentence
  (e.g. "how long does X take", "what does X mean", "what temperature for X"). If it can be answered
  in one short sentence with no follow-up needed, don't suggest it.
- Be specific (not "houseplant care tips" but e.g. "why your pothos leaves are turning yellow in winter").
- No medical, legal, or financial claims requiring professional accuracy.
- No duplicate/near-duplicate ideas.
- Return ONLY a JSON array of strings, nothing else. No markdown fences.
"""

    raw = call_gemini(prompt, temperature=1.0)
    raw = raw.strip()
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()

    try:
        new_topics = json.loads(raw)
    except json.JSONDecodeError:
        print("WARNING: could not parse topic suggestions, skipping refill this run.", file=sys.stderr)
        return state

    added = 0
    for t in new_topics:
        if isinstance(t, str) and t.lower() not in used_lower:
            state["queue"].append(t)
            used_lower.add(t.lower())
            added += 1

    print(f"Refilled queue with {added} new topics from niche '{niche['name']}'.")
    return state


def generate_page(topic):
    prompt = f"""Write a genuinely helpful, well-organized article for a website, on this topic:

"{topic}"

Requirements:
- Write like a knowledgeable person sharing real, specific, useful advice or information - not generic filler.
- Include concrete specifics (numbers, examples, steps) wherever relevant instead of vague statements.
- Do not make medical, legal, or financial claims that require professional certification.
- Do not fabricate statistics, studies, or sources.
- Length: 500-800 words.
- Structure with a few clear headings (use Markdown ##).
- If the topic is list/idea/comparison-shaped, actually deliver multiple distinct options with enough
  specific detail on each that skimming the list is worth more than a one-line summary would be.
- Include 1-3 relevant outbound links to genuine, well-known reference sources (e.g. Wikipedia for a
  concept, an official brand/manufacturer homepage if naming a specific product category) using
  Markdown link syntax [text](url). Only link to real domains you're confident exist - if unsure,
  skip the link rather than guess at a URL.
- Do not include affiliate links or tracking parameters - those are added separately, not by you.
- Do not include a title/H1 - start directly with an intro paragraph.
- Tone: plain, direct, conversational - avoid corporate/marketing language and avoid AI-sounding phrases like "in today's world" or "in conclusion".

Return ONLY the article body in Markdown, nothing else.
"""
    return call_gemini(prompt, temperature=0.85)


def write_post(topic, body):
    today = datetime.date.today()
    slug = slugify(topic)
    filename = f"{today.isoformat()}-{slug}.md"
    path = os.path.join(POSTS_DIR, filename)

    front_matter = (
        "---\n"
        f"title: \"{topic.replace(chr(34), chr(39))}\"\n"
        f"date: {today.isoformat()} 08:00:00 +0000\n"
        "layout: post\n"
        "---\n\n"
    )

    with open(path, "w") as f:
        f.write(front_matter)
        f.write(body.strip())
        f.write("\n")

    print(f"Wrote {path}")


def main():
    os.makedirs(POSTS_DIR, exist_ok=True)
    state = load_json(USED_PATH)
    seeds = load_json(SEED_PATH)

    state = refill_queue_if_needed(state, seeds)

    n = min(PAGES_PER_RUN, len(state["queue"]))
    if n == 0:
        print("Queue empty and could not refill. Nothing generated this run.")
        save_json(USED_PATH, state)
        return

    for _ in range(n):
        topic = state["queue"].pop(0)
        print(f"Generating: {topic}")
        try:
            body = generate_page(topic)
            write_post(topic, body)
            state["used_topics"].append(topic)
        except Exception as e:
            print(f"Failed on topic '{topic}': {e}", file=sys.stderr)
            state["queue"].append(topic)  # put it back for next run
        time.sleep(2)  # small delay between API calls

    save_json(USED_PATH, state)
    print(f"Done. Generated {n} pages this run.")


if __name__ == "__main__":
    main()
