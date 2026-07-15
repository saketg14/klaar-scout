import os
import copy
import re
import json
import time
import base64
import anthropic
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, Response, stream_with_context

app = Flask(__name__)

COMPETITORS = {
    "klaar": {
        "name": "Klaar",
        "url": "https://www.klaarhq.com",
        "color": "#8C52FD",
        "role": "our_product"
    },
    "cultureamp": {
        "name": "Culture Amp",
        "url": "https://www.cultureamp.com",
        "color": "#FF4D00",
        "role": "competitor"
    },
    "lattice": {
        "name": "Lattice",
        "url": "https://lattice.com",
        "color": "#4F46E5",
        "role": "competitor"
    },
    "15five": {
        "name": "15Five",
        "url": "https://www.15five.com",
        "color": "#059669",
        "role": "competitor"
    },
    "performyard": {
        "name": "PerformYard",
        "url": "https://www.performyard.com",
        "color": "#D97706",
        "role": "competitor"
    },
    "leapsome": {
        "name": "Leapsome",
        "url": "https://www.leapsome.com",
        "color": "#0EA5E9",
        "role": "competitor"
    },
    "betterworks": {
        "name": "Betterworks",
        "url": "https://www.betterworks.com",
        "color": "#8B5CF6",
        "role": "competitor"
    }
}

SUBPAGES = {
    "klaar":        ["/pricing", "/platform", "/customers", "/blog"],
    "cultureamp":   ["/pricing", "/platform", "/customers", "/resources"],
    "lattice":      ["/pricing", "/platform", "/customers", "/ai"],
    "15five":       ["/pricing", "/products", "/customers", "/blog"],
    "performyard":  ["/pricing", "/product-tour", "/customers", "/resources"],
    "leapsome":     ["/pricing", "/platform", "/customers", "/resources"],
    "betterworks":  ["/pricing", "/platform", "/customers", "/resources"]
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

KLAAR_EDGES = (
    "1. Predictive intelligence: Klaar tells you what is coming, not what already happened. "
    "Every other platform in the category is a rear view mirror. "
    "2. Auto integration with 50+ tools (Salesforce, Jira, HubSpot, Slack, ADP, HiBob and more): "
    "goals update from the actual work being done, zero double entry. The AI is the product, "
    "the integrations are the plumbing that feeds it."
)

CTA_WORDS = ["demo", "trial", "get started", "start free", "sign up", "book a", "contact sales",
             "talk to", "request", "buy now", "see pricing", "watch", "schedule"]

PRICING_SIGNALS = ["$", "per user", "per month", "per seat", "/mo", "/month", "/user",
                   "contact sales", "most popular", "free trial", "no credit card",
                   "billed annually", "billed monthly", "annual", "save "]

PROOF_SIGNALS = ["case study", "case studies", "trusted by", "customer story", "customers",
                 "testimonial", "results", "roi", "g2", "rated"]

# Fixed scoring rubric - same every run
SCORING_RUBRIC = """
SCORING RUBRIC (use these exact criteria, score 0-10):

above_the_fold (max 10):
- 3pts: Headline is a clear value proposition (not a slogan or framework name)
- 2pts: Subhead explains WHO it is for and WHAT problem it solves
- 2pts: Primary CTA is specific and low-friction
- 2pts: No competing announcements or banners stealing attention
- 1pt: Social proof signal visible above fold

structure_layout (max 10):
- 3pts: Single dominant eye path
- 3pts: Navigation does not expose every product before visitor is qualified
- 2pts: Page breathes, not a wall of content
- 2pts: Logical narrative arc from problem to solution to proof to CTA

pricing_psychology (max 10):
- 2pts: Pricing is publicly visible
- 2pts: Clear tier structure with obvious recommended option
- 2pts: Annual vs monthly toggle with savings shown
- 2pts: Risk reducer present (free trial, money-back, no credit card)
- 2pts: Feature gating makes upgrade path obvious

proof_case_studies (max 10):
- 3pts: Logo wall with recognizable brand names
- 3pts: Case studies include specific metrics
- 2pts: Testimonials from named individuals with title and company
- 2pts: Proof appears early, above fold or within first scroll

messaging_conversion (max 10):
- 3pts: Value prop is mechanistic, explains HOW it works
- 2pts: Positioning is specific, who it is for and who it is not for
- 2pts: CTA strategy has multiple commitment levels
- 2pts: Tone is differentiated, not generic enterprise-speak
- 1pt: No friction points blocking qualified buyers
"""


def fetch(url, timeout=15):
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def extract_signals(html, path="/"):
    soup = BeautifulSoup(html, "html.parser")
    headings = []
    for tag in soup.find_all(["h1", "h2", "h3"]):
        t = " ".join(tag.get_text(separator=" ").split())
        if t and len(t) < 140:
            headings.append(f"{tag.name}: {t}")
    headings = headings[:25]

    ctas = []
    for el in soup.find_all(["a", "button"]):
        t = " ".join(el.get_text(separator=" ").split()).lower()
        if t and len(t) < 40 and any(w in t for w in CTA_WORDS):
            ctas.append(t)
    ctas = list(dict.fromkeys(ctas))[:15]

    logo_imgs = sum(1 for img in soup.find_all("img") if "logo" in (img.get("alt") or "").lower())

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    low = text.lower()

    pricing_hits = sorted({s for s in PRICING_SIGNALS if s in low})
    proof_hits = sorted({s for s in PROOF_SIGNALS if s in low})

    return {
        "path": path,
        "above_the_fold": text[:600],
        "headings": headings,
        "ctas": ctas,
        "logo_img_count": logo_imgs,
        "pricing_signals": pricing_hits,
        "proof_signals": proof_hits,
        "text": text[:4000],
    }


COOKIE_SELECTORS = [
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Accept cookies')",
    "button:has-text('Accept')",
    "button:has-text('I agree')",
    "button:has-text('Got it')",
    "button:has-text('Allow all')",
    "[id*='accept']",
    "[class*='accept']",
]


def dismiss_cookies(page):
    for sel in COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=800):
                btn.click(timeout=800)
                page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    return False


def take_competitor_screenshots(key, info):
    paths = SCREENSHOT_PATHS.get(key, ["/", "/pricing", "/customers"])
    labels = ["home", "pricing", "proof"]
    result = {}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=['--no-sandbox', '--disable-setuid-sandbox',
                      '--disable-dev-shm-usage', '--disable-gpu']
            )
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            for label, path in zip(labels, paths):
                url = info["url"] if path == "/" else info["url"] + path
                print(f"  [screenshot] {info['name']} {path}...")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1500)
                    dismiss_cookies(page)
                    ss = page.screenshot(type="jpeg", quality=60, full_page=False)
                    result[label] = base64.b64encode(ss).decode('utf-8')
                    print(f"  [screenshot] {info['name']} {path} OK")
                except Exception as e:
                    print(f"  [screenshot] {info['name']} {path} FAILED: {e}")
            browser.close()
    except Exception as e:
        print(f"  [screenshot] browser launch failed for {info['name']}: {e}")
    return result


SCREENSHOT_PATHS = {
    "cultureamp":  ["/", "/pricing", "/customers"],
    "lattice":     ["/", "/pricing", "/customers"],
    "15five":      ["/", "/pricing", "/customers"],
    "performyard": ["/", "/pricing", "/customers"],
    "leapsome":    ["/", "/pricing", "/customers"],
    "betterworks": ["/", "/pricing", "/customers"],
    "klaar":       ["/", "/pricing", "/platform"],
}


def scrape_competitor(info, paths):
    pages = []
    try:
        pages.append(extract_signals(fetch(info["url"]), "/"))
        print(f"  [scrape] {info['name']} homepage OK")
    except Exception as e:
        print(f"  [scrape] {info['name']} homepage FAILED: {e}")
        pages.append({"path": "/", "error": str(e), "text": "", "headings": [],
                      "ctas": [], "pricing_signals": [], "proof_signals": [],
                      "above_the_fold": "", "logo_img_count": 0})
    for path in paths:
        try:
            pages.append(extract_signals(fetch(info["url"] + path, timeout=10), path))
            print(f"  [scrape] {info['name']} {path} OK")
            time.sleep(0.4)
        except Exception as e:
            print(f"  [scrape] {info['name']} {path} skipped: {e}")
    return pages


def build_digest(name, url, pages):
    out = [f"COMPANY: {name}", f"URL: {url}", "", "PAGE INVENTORY: " +
           ", ".join(p["path"] for p in pages)]
    for p in pages:
        out.append("")
        out.append(f"=== PAGE {p['path']} ===")
        if p.get("error"):
            out.append(f"(could not load: {p['error']})")
            continue
        out.append("ABOVE THE FOLD: " + p["above_the_fold"])
        if p["headings"]:
            out.append("HEADINGS (in order): " + " | ".join(p["headings"]))
        if p["ctas"]:
            out.append("CTAs: " + ", ".join(p["ctas"]))
        if p["pricing_signals"]:
            out.append("PRICING CUES PRESENT: " + ", ".join(p["pricing_signals"]))
        if p["proof_signals"]:
            out.append(f"PROOF CUES PRESENT: {', '.join(p['proof_signals'])} "
                       f"(logo images: {p['logo_img_count']})")
        out.append("BODY: " + p["text"])
    return "\n".join(out)[:9000]


COMPETITOR_SCHEMA = """{
  "above_the_fold": {"headline": "", "subhead": "", "primary_cta": "", "why": ""},
  "structure_layout": {"hierarchy_read": "", "density": "", "why": ""},
  "pricing_psychology": {"tier_structure": "", "anchoring": "", "most_popular_nudge": "", "hidden_behind_contact_sales": "", "annual_vs_monthly": "", "feature_gating": "", "risk_reducers": "", "why": ""},
  "proof_case_studies": {"logo_wall": "", "case_study_construction": "", "placement_sequencing": "", "testimonial_style": "", "recency_relevance": "", "why": ""},
  "messaging_conversion": {"value_proposition": "", "positioning": "", "cta_strategy": "", "friction_points": "", "tone_differentiation": "", "why": ""},
  "scores": {"above_the_fold": 0, "structure_layout": 0, "pricing_psychology": 0, "proof_case_studies": 0, "messaging_conversion": 0},
  "score_breakdown": {"above_the_fold": "", "structure_layout": "", "pricing_psychology": "", "proof_case_studies": "", "messaging_conversion": ""}
}"""

KLAAR_SCHEMA = """{
  "above_the_fold": {"headline": "", "subhead": "", "primary_cta": "", "why": ""},
  "structure_layout": {"hierarchy_read": "", "density": "", "why": ""},
  "pricing_psychology": {"tier_structure": "", "anchoring": "", "most_popular_nudge": "", "hidden_behind_contact_sales": "", "annual_vs_monthly": "", "feature_gating": "", "risk_reducers": "", "why": ""},
  "proof_case_studies": {"logo_wall": "", "case_study_construction": "", "placement_sequencing": "", "testimonial_style": "", "recency_relevance": "", "why": ""},
  "messaging_conversion": {"value_proposition": "", "positioning": "", "cta_strategy": "", "friction_points": "", "tone_differentiation": "", "why": ""},
  "scores": {"above_the_fold": 0, "structure_layout": 0, "pricing_psychology": 0, "proof_case_studies": 0, "messaging_conversion": 0},
  "score_breakdown": {"above_the_fold": "", "structure_layout": "", "pricing_psychology": "", "proof_case_studies": "", "messaging_conversion": ""},
  "vs_field": {
    "above_the_fold": "how Klaar compares to competitors on this section in one sentence",
    "structure_layout": "how Klaar compares to competitors on this section in one sentence",
    "pricing_psychology": "how Klaar compares to competitors on this section in one sentence",
    "proof_case_studies": "how Klaar compares to competitors on this section in one sentence",
    "messaging_conversion": "how Klaar compares to competitors on this section in one sentence",
    "biggest_gap": "the single most important thing Klaar must fix on its website right now",
    "biggest_strength": "the single strongest thing Klaar already does better than competitors"
  }
}"""


def competitor_prompt(digest):
    return (
        "You are a conversion strategist tearing down a competitor website. "
        "Apply the scoring rubric below exactly.\n\n"
        + SCORING_RUBRIC +
        "\n\nPAGE DATA:\n" + digest +
        "\n\nReturn ONLY valid JSON, no markdown fences, no preamble:\n"
        + COMPETITOR_SCHEMA
    )


def klaar_prompt(digest, competitor_scores_summary):
    return (
        "You are a conversion strategist analyzing Klaar's own website klaarhq.com. "
        "Apply the same scoring rubric used for competitors so scores are directly comparable.\n\n"
        + SCORING_RUBRIC +
        "\n\nKLAAR'S PAGE DATA:\n" + digest +
        "\n\nCOMPETITOR AVERAGE SCORES FOR CONTEXT:\n" + competitor_scores_summary +
        "\n\nKLAAR'S TWO REAL EDGES:\n" + KLAAR_EDGES +
        "\n\nIn the vs_field section, compare Klaar directly to the competitor average scores above. "
        "Be brutally honest - this is internal analysis for the founders.\n\n"
        "Return ONLY valid JSON, no markdown fences, no preamble:\n"
        + KLAAR_SCHEMA
    )


RECO_SCHEMA = """{
  "executive_summary": "2-3 sentences max on where Klaar stands against the field",
  "recommendations": {
    "copy": [{"move": "", "observed_in": "", "why": ""}],
    "avoid": [{"pattern": "", "why": ""}],
    "fix": [{"change": "", "page": "", "priority": "high|medium|low", "tied_to": ""}],
    "differentiate": [{"move": "", "anchor": "predictive intelligence|integration depth", "why": ""}]
  }
}"""



PER_COMPETITOR_RECO_SCHEMA = """{
  "vs_summary": "2 sentences: what this competitor does better than Klaar and what Klaar does better",
  "steal": [{"move": "", "why": "one sentence"}],
  "counter": [{"their_weakness": "", "klaar_move": "", "why": "one sentence"}],
  "watch_out": "one sentence on the single biggest threat this competitor poses to Klaar"
}"""


def per_competitor_reco_prompt(competitor_name, competitor_teardown, klaar_digest):
    return (
        f"You are a conversion strategist comparing Klaar (klaarhq.com) specifically against {competitor_name}.\n\n"
        f"KLAAR'S SITE DATA:\n{klaar_digest}\n\n"
        f"{competitor_name.upper()} TEARDOWN:\n{json.dumps(competitor_teardown)[:4000]}\n\n"
        f"KLAAR'S TWO REAL EDGES:\n{KLAAR_EDGES}\n\n"
        f"Generate specific recommendations for Klaar based ONLY on this one competitor.\n"
        f"steal: 2 things {competitor_name} does on their website that Klaar should copy.\n"
        f"counter: 2 weaknesses {competitor_name} has that Klaar can directly exploit.\n"
        f"Be specific and punchy. One sentence per field. No generic advice.\n\n"
        f"Return ONLY valid JSON, no fences, no preamble:\n"
        + PER_COMPETITOR_RECO_SCHEMA
    )

def recommendation_prompt(klaar_digest, teardowns):
    return (
        "You are a conversion strategist advising Klaar on klaarhq.com. "
        "You have Klaar's own site data and structured teardowns of competitors.\n\n"
        "KLAAR'S OWN SITE DATA:\n" + klaar_digest +
        "\n\nCOMPETITOR TEARDOWNS (JSON):\n" + json.dumps(teardowns)[:7000] +
        "\n\nKLAAR'S TWO REAL EDGES:\n" + KLAAR_EDGES +
        "\n\nReturn ONLY valid JSON in exactly this shape, no fences, no preamble:\n"
        + RECO_SCHEMA +
        "\n\nKeep each recommendation to 1-2 sentences max. Be specific and punchy. "
        "Limit to 3 items per category."
    )


def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        raise


def call_claude(client, prompt, max_tokens=3500):
    print(f"  [claude] calling API (max_tokens={max_tokens})...")
    full = ""
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            full += chunk
    print(f"  [claude] got {len(full)} chars back")
    return parse_json(full)


def build_competitor_scores_summary(teardowns):
    """Build a text summary of competitor average scores for the Klaar prompt."""
    if not teardowns:
        return "No competitor scores available."
    keys = ["above_the_fold", "structure_layout", "pricing_psychology", "proof_case_studies", "messaging_conversion"]
    labels = ["Above the Fold", "Structure & Layout", "Pricing Psychology", "Proof & Cases", "Messaging"]
    lines = []
    for k, l in zip(keys, labels):
        vals = [t["scores"][k] for t in teardowns if t.get("scores") and isinstance(t["scores"].get(k), (int, float))]
        if vals:
            avg = round(sum(vals) / len(vals), 1)
            best_competitor = max(teardowns, key=lambda t: t.get("scores", {}).get(k, 0) if t.get("scores") else 0)
            lines.append(f"{l}: field average {avg}/10, best competitor is {best_competitor['name']} with {best_competitor.get('scores', {}).get(k, 0)}/10")
    return "\n".join(lines)


def sse(payload):
    return f"data: {json.dumps(payload)}\n\n"


@app.route("/")
def index():
    return render_template("index.html", competitors=COMPETITORS)


@app.route("/api/scrape-and-analyze")
def scrape_and_analyze():
    def generate():
        try:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                yield sse({"status": "error", "message": "ANTHROPIC_API_KEY not set"})
                return

            client = anthropic.Anthropic(api_key=api_key)

            # 1. Take screenshots for competitors + Klaar
            screenshots = {}
            for key, info in COMPETITORS.items():
                yield sse({"status": "scraping", "message": f"Taking screenshots of {info['name']}..."})
                print(f"\n[SCREENSHOTS] {info['name']}")
                screenshots[key] = take_competitor_screenshots(key, info)

            # 2. Scrape text content for everyone
            digests = {}
            for key, info in COMPETITORS.items():
                print(f"\n[SCRAPING] {info['name']}")
                yield sse({"status": "scraping", "message": f"Scraping {info['name']}..."})
                pages = scrape_competitor(info, SUBPAGES.get(key, []))
                digests[key] = build_digest(info["name"], info["url"], pages)
                print(f"[SCRAPING] {info['name']} digest built ({len(digests[key])} chars)")

            # 3. Competitor teardowns
            teardowns = []
            for key, info in COMPETITORS.items():
                if info["role"] != "competitor":
                    continue
                print(f"\n[TEARDOWN] {info['name']}")
                yield sse({"status": "analyzing", "message": f"Analyzing {info['name']}..."})
                try:
                    raw = call_claude(client, competitor_prompt(digests[key]))
                    teardown = copy.deepcopy(raw)
                    teardown["key"] = key
                    teardown["name"] = info["name"]
                    teardown["url"] = info["url"]
                    teardown["color"] = info["color"]
                    teardown["screenshots"] = screenshots.get(key, {})
                    teardowns.append(teardown)
                    print(f"[TEARDOWN] {info['name']} done")
                    yield sse({"status": "competitor_done", "data": teardown})

                    # Per-competitor recommendations vs Klaar
                    try:
                        per_reco = call_claude(client, per_competitor_reco_prompt(
                            info['name'], teardown, digests.get('klaar', '')))
                        per_reco = copy.deepcopy(per_reco)
                        per_reco['key'] = key
                        per_reco['name'] = info['name']
                        yield sse({"status": "competitor_reco_done", "data": per_reco})
                        print(f"[PER-RECO] {info['name']} done")
                    except Exception as re:
                        print(f"[PER-RECO ERROR] {info['name']}: {re}")
                except Exception as e:
                    print(f"[TEARDOWN ERROR] {info['name']}: {e}")
                    yield sse({"status": "warn", "message": f"{info['name']} teardown failed: {e}"})

            # 4. Klaar own site analysis - runs after all competitors so it can compare
            print(f"\n[KLAAR] analyzing own site")
            yield sse({"status": "analyzing", "message": "Analyzing Klaar's own website..."})
            try:
                scores_summary = build_competitor_scores_summary(teardowns)
                raw_klaar = call_claude(client, klaar_prompt(digests.get("klaar", ""), scores_summary), max_tokens=4000)
                klaar_analysis = copy.deepcopy(raw_klaar)
                klaar_analysis["key"] = "klaar"
                klaar_analysis["name"] = "Klaar"
                klaar_analysis["url"] = "https://www.klaarhq.com"
                klaar_analysis["color"] = "#8C52FD"
                klaar_analysis["screenshots"] = screenshots.get("klaar", {})
                klaar_analysis["is_own_site"] = True
                print(f"[KLAAR] done")
                yield sse({"status": "klaar_done", "data": klaar_analysis})
            except Exception as e:
                print(f"[KLAAR ERROR]: {e}")
                yield sse({"status": "warn", "message": f"Klaar analysis failed: {e}"})

            # 5. Recommendations
            print(f"\n[RECOS] building recommendations, {len(teardowns)} teardowns available")
            yield sse({"status": "analyzing", "message": "Building recommendations for klaarhq.com..."})
            try:
                recos = call_claude(client,
                                    recommendation_prompt(digests.get("klaar", ""), teardowns),
                                    max_tokens=4000)
                print("[RECOS] done")
                yield sse({"status": "recommendations_done", "data": recos})
            except Exception as e:
                print(f"[RECOS ERROR]: {e}")
                yield sse({"status": "warn", "message": f"Recommendation build failed: {e}"})

            print("\n[DONE]")
            yield sse({"status": "done"})

        except Exception as e:
            print(f"\n[FATAL ERROR] {e}")
            import traceback
            traceback.print_exc()
            yield sse({"status": "error", "message": f"Fatal error: {e}"})

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
