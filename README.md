# klaar-scout

A Flask app that scrapes the marketing websites of six competitors and Klaar, then uses the Claude API to score each site on a fixed rubric and suggest what Klaar should copy or counter.

## What one run does

- **7 sites:** 6 competitors (Culture Amp, Lattice, 15Five, PerformYard, Leapsome, Betterworks) plus Klaar's own site
- **35 pages scraped:** the homepage and 4 subpages per site (pricing, customers, and two product or content pages)
- **21 screenshots:** home, pricing, and customers (platform for Klaar) for each site, taken with headless Chromium
- **13 Claude calls:** 6 competitor teardowns, 6 head-to-head recommendations for Klaar, and 1 analysis of Klaar's site against the competitor averages
- **5 scoring areas, each scored 0 to 10:** above the fold, structure and layout, pricing psychology, proof and case studies, messaging and conversion
- **15-day cache:** results are saved and served from cache until they are 15 days old, unless you force a refresh

## Why I built it

I built this during my internship at Klaar, an HR tech startup. Comparing Klaar's website against competitors was manual work: open each site, read the pricing and customer pages, take notes, and write up what each one does well. I wanted the same comparison every time, scored against the same criteria, without redoing the reading by hand.

## How it works

1. **Screenshots.** Playwright opens each site, dismisses cookie banners, and captures three pages as JPEGs.
2. **Scraping.** `requests` and BeautifulSoup pull each page and extract headings (h1 to h3), call-to-action buttons, logo image counts, pricing keywords (for example "per user", "billed annually", "contact sales"), social proof keywords, and the first 4,000 characters of body text. Each site is condensed into a text digest of at most 9,000 characters.
3. **Competitor teardowns.** Each competitor digest goes to Claude (`claude-sonnet-4-6`) with the scoring rubric in `app.py` (`SCORING_RUBRIC`). Claude returns JSON with a score and reasoning for each of the 5 areas.
4. **Head-to-head recommendations.** For each competitor, a second call compares it against Klaar's site and returns two things to copy, two weaknesses to counter, and one risk to watch.
5. **Klaar's site.** Klaar is scored last, on the same rubric, with the competitor averages as context, so its scores are directly comparable.
6. **Output.** Results stream to the browser over server-sent events as each call finishes. The page shows a radar chart across all competitors, a tab per competitor with screenshots and section-by-section notes, and a summary of where Klaar is ahead of or behind the field average.

## How to run

You need Python 3.9 or newer (the minimum for the pinned Playwright version) and an Anthropic API key.

```bash
pip install -r requirements.txt
playwright install chromium
export ANTHROPIC_API_KEY=your-key-here
python app.py
```

Open http://localhost:5000 and click **Run teardown**. A full run makes 13 API calls. If a cached result less than 15 days old exists, the page loads it instead; use **Force refresh** to run again.

With Docker:

```bash
docker build -t klaar-scout .
docker run -p 8080:8080 -e ANTHROPIC_API_KEY=your-key-here klaar-scout
```

Then open http://localhost:8080.

Results are written to `scout_cache.json` in the project folder. It is in `.gitignore` because it holds scraped page text and base64 screenshots.

## Results

The manual version of this comparison took about [MANUAL TIME]. A full run takes about [RUN TIME]. Both numbers are my estimates, not measured by the code.

## Limitations

- Scores come from Claude reading a text digest and following the rubric. They are consistent in structure but not deterministic, so the same site can score differently between runs.
- The scraper reads static HTML. Content that only loads through JavaScript is missed in the text digest, though it does appear in the screenshots.
- The competitor list and page paths are hardcoded in `app.py` (`COMPETITORS`, `SUBPAGES`, `SCREENSHOT_PATHS`). Sites that change their URLs will show up as skipped pages in the server log.
- There is no authentication on the API routes. Do not deploy it publicly without adding some, since anyone with the URL can trigger a full run on your API key.
