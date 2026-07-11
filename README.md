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
- `.github/workflows/generate-content.yml` runs daily (cron, or trigger manually from the
  Actions tab), generates 3-4 new posts via Gemini, commits them to `_posts/`.
- That commit triggers `.github/workflows/deploy.yml`, which builds the Jekyll site and
  publishes it to GitHub Pages.
- `topics/used.json` tracks what's been published so topics don't repeat. You can edit
  this file by hand any time (e.g. to remove something you don't want live).

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
