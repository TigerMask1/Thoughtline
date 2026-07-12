#!/usr/bin/env python3
"""
Daily content generator.

What it does, in order:
1. Loads topics/seed-niches.json (your list of niches) and topics/used.json (queue + history).
2. If the queue is low, asks Gemini to expand a niche into new long-tail topic ideas,
   filters out anything already used, and adds the rest to the queue.
3. Pops PAGES_PER_RUN topics off the queue. For each:
   - Asks Gemini for a structured page: SEO title, meta description, image search query, and body.
   - Fetches a real, attributed, openly-licensed image from Openverse to match the topic.
   - Writes a full page to _posts/ with SEO front matter (title, description, image, credit).
4. Marks each topic as used so it's never generated twice.

Run with: python scripts/generate.py
Requires env var GEMINI_API_KEY. No key needed for Openverse (public API).
"""

import json
import os
import re
import sys
import time
import random
import datetime
import urllib.request
import urllib.parse

PAGES_PER_RUN = int(os.environ.get("PAGES_PER_RUN", "1"))
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


def strip_json_fences(raw):
    raw = raw.strip()
    return re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()


def fetch_openverse_image(query):
    """Fetch one openly-licensed, attributable image from Openverse. No API key required.
    Returns dict with url/title/creator/creator_url/license/foreign_landing_url, or None."""
    try:
        params = urllib.parse.urlencode({
            "q": query,
            "license_type": "commercial,modification",
            "page_size": 6,
            "mature": "false",
        })
        req = urllib.request.Request(
            f"https://api.openverse.org/v1/images/?{params}",
            headers={"User-Agent": "thoughtline-content-bot/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = data.get("results", [])
        for r in results:
            # Prefer results with a real image url and known creator for clean attribution
            if r.get("url") and r.get("license"):
                return {
                    "url": r["url"],
                    "title": r.get("title") or query,
                    "creator": r.get("creator") or "Unknown",
                    "creator_url": r.get("creator_url") or "",
                    "license": (r.get("license") or "").upper(),
                    "license_url": r.get("license_url") or "",
                    "source_page": r.get("foreign_landing_url") or r.get("url"),
                }
    except Exception as e:
        print(f"WARNING: image fetch failed for '{query}': {e}", file=sys.stderr)
    return None


def fetch_trending_searches(geo="US"):
    """Pull today's live trending search terms from Google Trends' public RSS feed.
    No API key needed. Returns a list of plain strings, or [] if the fetch fails
    (endpoint changes, network issue, etc.) - callers must handle the empty case."""
    try:
        req = urllib.request.Request(
            f"https://trends.google.com/trending/rss?geo={geo}",
            headers={"User-Agent": "Mozilla/5.0 (compatible; thoughtline-content-bot/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
        titles = re.findall(r"<title>(?!Daily Search Trends)(.*?)</title>", raw)
        return [t.strip() for t in titles if t.strip()][:25]
    except Exception as e:
        print(f"WARNING: could not fetch live trending searches: {e}", file=sys.stderr)
        return []


def refill_queue_if_needed(state, seeds):
    if len(state["queue"]) >= QUEUE_LOW_WATERMARK:
        return state

    niches = seeds.get("niches", [])
    if not niches:
        print("No niches defined in topics/seed-niches.json - add some.", file=sys.stderr)
        return state

    niche = random.choice(niches)
    used_lower = {t.lower() for t in state["used_topics"]} | {t.lower() for t in state["queue"]}

    trending = fetch_trending_searches()
    trending_block = ""
    if trending:
        trending_block = (
            "\nHere is what's actually trending in live search RIGHT NOW (Google Trends, today):\n"
            + "\n".join(f"- {t}" for t in trending)
            + "\n\nIf any of these genuinely fit this niche and can be reframed as a safe, useful "
              "buying-guide/list/comparison topic, prioritize using them (e.g. if 'sauna blankets' is "
              "trending and the niche is home/wellness-adjacent, suggest 'what to look for when buying "
              "a sauna blanket' - a buying-guide reframe, never a health-effect claim). Most trending "
              "terms won't fit this niche (celebrity news, sports, etc.) - ignore those completely and "
              "fall back to your own niche knowledge for the rest of the topics.\n"
        )

    prompt = f"""You are helping plan content for a niche site about: "{niche['name']}"
Notes on scope: {niche.get('notes', 'none')}
{trending_block}
Suggest {TOPICS_TO_GENERATE_PER_NICHE} specific, genuinely useful long-tail article topics for this niche.
Rules:
- Favor list, comparison, and compound/specific formats: "X ideas for [specific person/situation]",
  "X vs Y for [specific context]", "what to look for when buying [specific thing]". These give a reason
  to click through and browse rather than getting fully answered in a single AI-generated snippet.
- Avoid single-fact phrasing that a search engine's AI answer box could fully resolve in one sentence
  (e.g. "how long does X take", "what does X mean", "what temperature for X"). If it can be answered
  in one short sentence with no follow-up needed, don't suggest it.
- Be specific (not "houseplant care tips" but e.g. "why your pothos leaves are turning yellow in winter").
- No medical, legal, or financial claims requiring professional accuracy. For any wellness/health-adjacent
  product angle, frame it as a buying-guide/comparison ("what to look for when buying X") rather than a
  claim about what the product does for the body.
- No duplicate/near-duplicate ideas.
- Return ONLY a JSON array of strings, nothing else. No markdown fences.
"""

    raw = call_gemini(prompt, temperature=1.0)
    raw = strip_json_fences(raw)

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

    trend_note = f" (informed by {len(trending)} live trending terms)" if trending else " (live trends unavailable this run, used niche knowledge only)"
    print(f"Refilled queue with {added} new topics from niche '{niche['name']}'{trend_note}.")
    return state


def generate_page(topic):
    """Returns dict: seo_title, meta_description, image_query, article_markdown"""
    prompt = f"""Write a genuinely helpful, well-organized article for a website, on this topic:

"{topic}"

Requirements for the article body:
- Write like a knowledgeable person sharing real, specific, useful advice - not generic filler.
- Include concrete specifics (numbers, examples, steps) wherever relevant instead of vague statements.
- Do not make medical, legal, or financial claims that require professional certification.
- Do not fabricate statistics, studies, or sources.
- Length: 500-800 words.
- Structure with a few clear headings (Markdown ##).
- If the topic is list/idea/comparison-shaped, actually deliver multiple distinct options with enough
  specific detail on each that skimming the list is worth more than a one-line summary would be.
- Include 1-3 relevant outbound links to genuine, well-known reference sources (Wikipedia for a concept,
  an official brand/manufacturer homepage for a named product category) using Markdown link syntax
  [text](url). Only link to real domains you're confident exist - skip the link rather than guess a URL.
- Do not include affiliate links or tracking parameters.
- Do not include a title/H1 in the body - start directly with an intro paragraph.
- Tone: plain, direct, conversational - avoid corporate/marketing language and AI-sounding phrases like
  "in today's world" or "in conclusion".

Also produce SEO metadata:
- seo_title: a compelling, specific page title, 50-60 characters, front-loaded with the main keyword phrase.
- meta_description: 140-155 characters, includes the main keyword phrase naturally, written to earn a click
  from a search results page (specific benefit, not generic).
- image_query: a short (2-4 word) plain-English search phrase that would find a relevant, generic stock/
  editorial photo for this article on a stock photo site (e.g. "pottery studio hands" not "gift ideas").

Return ONLY a single JSON object with exactly these keys, nothing else, no markdown fences:
{{"seo_title": "...", "meta_description": "...", "image_query": "...", "article_markdown": "..."}}
"""
    raw = call_gemini(prompt, temperature=0.85)
    raw = strip_json_fences(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: treat entire response as the article body if structured parse fails
        print("WARNING: could not parse structured page JSON, using raw text as body.", file=sys.stderr)
        return {
            "seo_title": topic,
            "meta_description": "",
            "image_query": topic,
            "article_markdown": raw,
        }


def yaml_escape(s):
    return s.replace('"', "'").replace("\n", " ").strip()


def write_post(topic, page):
    today = datetime.date.today()
    slug = slugify(topic)
    filename = f"{today.isoformat()}-{slug}.md"
    path = os.path.join(POSTS_DIR, filename)

    title = yaml_escape(page.get("seo_title") or topic)
    description = yaml_escape(page.get("meta_description") or "")
    body = page.get("article_markdown", "").strip()

    image = fetch_openverse_image(page.get("image_query") or topic)

    front_matter_lines = [
        "---",
        f'title: "{title}"',
        f"date: {today.isoformat()} 08:00:00 +0000",
        "layout: post",
    ]
    if description:
        front_matter_lines.append(f'description: "{description}"')

    image_markdown = ""
    if image:
        front_matter_lines.append(f'image: "{image["url"]}"')
        front_matter_lines.append(f'image_credit: "{yaml_escape(image["creator"])}"')
        front_matter_lines.append(f'image_credit_url: "{image["creator_url"] or image["source_page"]}"')
        front_matter_lines.append(f'image_license: "{image["license"]}"')
        alt_text = yaml_escape(image.get("title") or topic)
        image_markdown = (
            f'\n![{alt_text}]({image["url"]})\n'
            f'*Photo via [Openverse]({image["source_page"]}) '
            f'· [{image["creator"] or "Unknown"}]({image["creator_url"] or image["source_page"]}) '
            f'· {image["license"]}*\n'
        )

    front_matter_lines.append("---")
    front_matter = "\n".join(front_matter_lines) + "\n\n"

    with open(path, "w") as f:
        f.write(front_matter)
        if image_markdown:
            f.write(image_markdown)
            f.write("\n")
        f.write(body)
        f.write("\n")

    print(f"Wrote {path}" + (" (with image)" if image else " (no image found, text only)"))


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
            page = generate_page(topic)
            write_post(topic, page)
            state["used_topics"].append(topic)
        except Exception as e:
            print(f"Failed on topic '{topic}': {e}", file=sys.stderr)
            state["queue"].append(topic)  # put it back for next run
        time.sleep(2)

    save_json(USED_PATH, state)
    print(f"Done. Generated {n} page(s) this run.")


if __name__ == "__main__":
    main()
