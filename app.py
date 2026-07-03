import os
import re
import json
import time
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

    logo_imgs = sum(
        1 for img in soup.find_all("img")
        if "logo" in (img.get("alt") or "").lower()
    )

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
  "above_the_fold": {"headline": "", "subhead": "", "primary_cta": "", "verdict": "working|not_working", "why": ""},
  "structure_layout": {"hierarchy_read": "", "density": "", "verdict": "working|not_working", "why": ""},
  "pricing_psychology": {"tier_structure": "", "anchoring": "", "most_popular_nudge": "", "hidden_behind_contact_sales": "", "annual_vs_monthly": "", "feature_gating": "", "risk_reducers": "", "verdict": "working|not_working", "why": ""},
  "proof_case_studies": {"logo_wall": "", "case_study_construction": "", "placement_sequencing": "", "testimonial_style": "", "recency_relevance": "", "verdict": "working|not_working", "why": ""},
  "messaging_conversion": {"value_proposition": "", "positioning": "", "cta_strategy": "", "friction_points": "", "tone_differentiation": "", "verdict": "working|not_working", "why": ""},
  "scores": {"above_the_fold": 0, "structure_layout": 0, "pricing_psychology": 0, "proof_case_studies": 0, "messaging_conversion": 0}
}"""


def competitor_prompt(digest):
    return (
        "You are a conversion strategist tearing down a competitor's website. "
        "Read the structured page data below and produce the teardown.\n\n"
        + digest +
        "\n\nReturn ONLY valid JSON in exactly this shape, no markdown fences, no preamble:\n"
        + COMPETITOR_SCHEMA +
        "\n\nFor the scores object, rate each section from 0-10 based on how well the competitor "
        "executes it. 10 = best in class, 0 = completely absent or broken. These scores will be "
        "used to generate comparison charts. Be objective and consistent across competitors.\n\n"
        "Where a page was not captured, say so plainly in the relevant field."
    )


RECO_SCHEMA = """{
  "executive_summary": "2-3 sentences max on where Klaar stands against the field",
  "klaar_teardown": {"above_the_fold_verdict": "", "biggest_weakness": "", "biggest_strength": ""},
  "recommendations": {
    "copy": [{"move": "", "observed_in": "", "why": ""}],
    "avoid": [{"pattern": "", "why": ""}],
    "fix": [{"change": "", "page": "", "priority": "high|medium|low", "tied_to": ""}],
    "differentiate": [{"move": "", "anchor": "predictive intelligence|integration depth", "why": ""}]
  }
}"""


def recommendation_prompt(klaar_digest, teardowns):
    return (
        "You are a conversion strategist advising Klaar on klaarhq.com. "
        "You have Klaar's own site data and structured teardowns of competitors.\n\n"
        "KLAAR'S OWN SITE DATA:\n" + klaar_digest +
        "\n\nCOMPETITOR TEARDOWNS (JSON):\n" + json.dumps(teardowns)[:7000] +
        "\n\nKLAAR'S TWO REAL EDGES:\n" + KLAAR_EDGES +
        "\n\nReturn ONLY valid JSON in exactly this shape, no fences, no preamble:\n"
        + RECO_SCHEMA +
        "\n\nKeep each recommendation to 1-2 sentences max. Be specific and punchy, not wordy. "
        "Limit to 3 items per category. Each fix must tie to a specific gap."
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

            digests = {}
            for key, info in COMPETITORS.items():
                print(f"\n[SCRAPING] {info['name']}")
                yield sse({"status": "scraping", "message": f"Scraping {info['name']}..."})
                pages = scrape_competitor(info, SUBPAGES.get(key, []))
                digests[key] = build_digest(info["name"], info["url"], pages)
                print(f"[SCRAPING] {info['name']} digest built ({len(digests[key])} chars)")

            teardowns = []
            for key, info in COMPETITORS.items():
                if info["role"] != "competitor":
                    continue
                print(f"\n[TEARDOWN] {info['name']}")
                yield sse({"status": "analyzing", "message": f"Tearing down {info['name']}..."})
                try:
                    teardown = call_claude(client, competitor_prompt(digests[key]))
                    teardown.update({"key": key, "name": info["name"],
                                     "url": info["url"], "color": info["color"]})
                    teardowns.append(teardown)
                    print(f"[TEARDOWN] {info['name']} done")
                    yield sse({"status": "competitor_done", "data": teardown})
                except Exception as e:
                    print(f"[TEARDOWN ERROR] {info['name']}: {e}")
                    yield sse({"status": "warn", "message": f"{info['name']} teardown failed: {e}"})

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
