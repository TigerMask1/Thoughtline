# Site setup

## One-time setup
1. Create a new GitHub repo, push this folder to it.
2. Repo Settings → Pages → Source: set to "GitHub Actions".
3. Repo Settings → Secrets and variables → Actions → New repository secret:
   - Name: `GEMINI_API_KEY`
   - Value: your Gemini API key
4. Edit `_config.yml`: set `title`, `description`, and `url` to your actual repo's Pages URL
   (e.g. `https://yourusername.github.io/yourrepo`).
5. Edit `topics/seed-niches.json` with the niches you actually want to cover. This is the
   main lever you control — pick things you know something about or genuinely want to build
   a resource around, not random keyword lists.

## How it runs
- `.github/workflows/generate-content.yml` fires 4x/day at staggered UTC times (each with a random
  0-50 min jitter added on top), generating **1 page per run** — so pages land at 4 different,
  non-obvious times across the day instead of arriving as one batch.
- Each page gets: an SEO title (50-60 chars), a real meta description (140-155 chars), a genuine
  attributed image pulled from Openverse (openly-licensed, no API key needed), Article structured
  data (JSON-LD) for search engines, and 2-3 internal links to related posts on your site.
- That commit triggers `.github/workflows/deploy.yml`, which builds the Jekyll site and publishes
  it to GitHub Pages.
- `topics/used.json` tracks what's been published so topics don't repeat.
- `robots.txt` points crawlers at the sitemap that `jekyll-sitemap` auto-generates.

## Images
- Images come from the [Openverse API](https://openverse.org) — openly-licensed (CC/public domain),
  no API key required, no cost. Each image is written with proper attribution (creator, license,
  source link) in the post front matter and as a caption under the image, which is a legal
  requirement of most CC licenses, not optional styling.
- If no suitable image is found for a topic, the page still generates - just without a hero image.
  Check `_posts/` occasionally for image quality; the Openverse query is only as good as the
  `image_query` Gemini generates.

## Topic sourcing (self-refilling)
- Whenever the queue drops below 6 topics, the script fetches Google's live daily trending
  searches (public RSS, no key needed) and asks Gemini to keep only the ones that genuinely fit
  one of your niches - reframed as a safe buying-guide/list topic, never a health/efficacy claim.
  Everything else (celebrity news, sports, unrelated trends) gets discarded.
- If the trends fetch fails for any reason (Google changes the endpoint, network hiccup), the
  script logs a warning and falls back to generating topics from niche knowledge alone - it
  never blocks a run.
- You still fully control direction via `topics/seed-niches.json` - trending terms only get
  used if they fit a niche you've already defined there.

## What this can't do
Being direct about limits, since overselling this would waste your time later:
- No pipeline can guarantee search traffic. Rankings also depend on backlinks, domain trust
  built over months, and real reader engagement - none of which a generator can manufacture.
  This setup maximizes the controllable half (structure, meta, real images, internal links,
  genuinely useful content, natural publish timing) - the rest is earned over time.
- Openverse image matches are only as good as the search query Gemini generates - spot check
  the first couple weeks.
- Google Trends' public feed can change format without notice; if topic refills stop working,
  check the Actions log for the "could not fetch live trending searches" warning first.

## Before turning on AdSense
- Apply for AdSense only once there's a reasonable amount of genuinely useful content live
  (Google reviews the site, not just individual pages).
- Once approved, put your AdSense client ID into `_config.yml` → `adsense_client`, and fill
  in the `data-ad-slot` values in `_layouts/post.html` with your actual ad unit slot IDs
  from the AdSense dashboard.

## Adjusting output
- Change `PAGES_PER_RUN` in `.github/workflows/generate-content.yml` to publish more/fewer
  pages per day.
- Change the cron schedule to run at a different time.
- Edit the prompts in `scripts/generate.py` (`generate_page` and the topic-expansion prompt
  in `refill_queue_if_needed`) to adjust tone, length, or constraints.

## Notes
- Model used is `gemini-flash-latest` — this always points at the latest Flash model. If you
  want to pin a specific version, edit `GEMINI_MODEL` in `scripts/generate.py`.
- Review `_posts/` occasionally. Automated generation with review beats fully unattended —
  catch anything factually shaky or off-tone before it accumulates.
