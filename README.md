# klaar-scout

Compares Klaar's marketing site against 6 competitors (Culture Amp, Lattice, 15Five, PerformYard, Leapsome, Betterworks) and scores each one on the same 5-area rubric.

## Why I built it

During my internship at Klaar, a Series A startup, the founders did this competitor research by hand: open each site, read the pricing and customer pages, take notes, and compare. That took about 3 hours. A run of this tool takes about 2 to 3 minutes. Both numbers are my estimates; the code does not measure them.

## How it works

One run covers 7 sites: the 6 competitors plus Klaar.

1. **Screenshots.** Playwright opens each site in headless Chromium, dismisses cookie banners, and captures 3 pages per site (home, pricing, customers), for 21 screenshots per run.
2. **Scraping.** `requests` and BeautifulSoup fetch the homepage and 4 subpages per site (35 pages in total) and pull out headings, call-to-action buttons, logo counts, pricing keywords, social proof keywords, and body text. Each site is condensed into a text digest of at most 9,000 characters.
3. **Scoring.** Each digest goes to Claude (`claude-sonnet-4-6`) with the rubric in `app.py` (`SCORING_RUBRIC`). Claude scores the site 0 to 10 on:
   - above the fold
   - structure and layout
   - pricing psychology
   - proof and case studies
   - messaging and conversion
4. **Recommendations.** For each competitor, a second call compares it with Klaar and returns what to steal, what to counter, and one thing to watch out for.
5. **Klaar.** Klaar's site is scored last, on the same rubric, against the competitor averages.

That is 13 streaming Claude calls per run: 6 competitor scores, 6 steal / counter / watch out calls, and 1 for Klaar. Results stream to the browser as each call finishes and show up as a radar chart, a tab per competitor with screenshots and notes, and a summary of where Klaar is ahead of or behind the average.

Results are cached in `scout_cache.json` for 15 days. Until the cache expires, the page loads from it instead of making new calls. **Force refresh** runs everything again.

## How to run it

You need Python 3.10 or newer and an Anthropic API key.

```bash
pip install -r requirements.txt
playwright install chromium
export ANTHROPIC_API_KEY=your-key-here
python app.py
```

Open http://localhost:5000 and click **Run teardown**.

With Docker:

```bash
docker build -t klaar-scout .
docker run -p 8080:8080 -e ANTHROPIC_API_KEY=your-key-here klaar-scout
```

Then open http://localhost:8080.

## Deployment

This is not deployed publicly. The version I ran during the internship has been taken down. The API routes have no authentication, so anyone who can reach a deployed copy can start a run on your API key. Add authentication before deploying it anywhere public.

## Limitations

- Scores come from Claude following a written rubric, so the same site can score differently between runs.
- The scraper reads raw HTML. Text that only appears after JavaScript runs is missed in the digest, though it shows up in the screenshots.
- The competitor list and page paths are hardcoded in `app.py` (`COMPETITORS`, `SUBPAGES`, `SCREENSHOT_PATHS`). If a site moves a page, it shows up as skipped in the server log.
