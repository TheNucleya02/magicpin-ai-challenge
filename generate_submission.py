"""
Direct submission generator — bypasses the HTTP bot server to call the Gemini
composer inline. Each of the 30 test pairs gets a fresh compose call with no
suppression interference.

Model: gemini-1.5-flash  →  free tier allows 1,500 req/day (vs 20 for 2.5-flash)
"""
import os, json, sys, time
from pathlib import Path
from google import genai
from google.genai import types

EXPANDED = Path(__file__).parent / "expanded"
API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL   = "gemini-1.5-flash"   # 1,500 req/day free tier — much higher than 2.5-flash's 20

def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)

def load_contexts():
    cats, merchants, customers, triggers = {}, {}, {}, {}
    for f in (EXPANDED / "categories").glob("*.json"):
        d = load_json(f); cats[d["slug"]] = d
    for f in (EXPANDED / "merchants").glob("*.json"):
        d = load_json(f); merchants[d["merchant_id"]] = d
    for f in (EXPANDED / "customers").glob("*.json"):
        d = load_json(f); customers[d["customer_id"]] = d
    for f in (EXPANDED / "triggers").glob("*.json"):
        d = load_json(f); triggers[d["id"]] = d
    return cats, merchants, customers, triggers

def compose(client, category, merchant, trigger, customer=None):
    voice   = category.get("voice", {})
    tone    = voice.get("tone", "collegial")
    taboos  = voice.get("taboos", [])
    langs   = merchant.get("identity", {}).get("languages", ["en"])
    is_hi   = "hi" in langs
    owner   = merchant.get("identity", {}).get("owner_first_name", "Partner")
    send_as = "merchant_on_behalf" if trigger.get("scope") == "customer" else "vera"

    prompt = f"""You are Vera, magicpin's merchant AI assistant composing a WhatsApp message.

RULES (all mandatory):
1. SPECIFICITY: Anchor on ≥1 verifiable fact from context — a number, ₹ price, date, stat, or citation. 
   Use exact prices like "Dental Cleaning @ ₹299", never "flat 10% off".
2. VOICE: Category="{category.get('slug')}". Tone={tone}. Never say: {json.dumps(taboos)}.
3. LANGUAGE: {"Write in natural Romanized Hinglish (English nouns + Hindi conversational glue). E.g. 'Aapke 78 lapsed patients ke liye ek reminder bhejna chahiye kya?'" if is_hi else "Write in professional English."}
4. NO URLS anywhere in body.
5. NO hallucination — anchor only on facts in the provided context. Do not invent citations, stats, or competitor names.
6. CTA must be the final sentence. Single CTA only.
7. Address merchant by first name: {owner}

CONTEXT:
## Category
{json.dumps(category, ensure_ascii=False, indent=2)}

## Merchant  
{json.dumps(merchant, ensure_ascii=False, indent=2)}

## Trigger
{json.dumps(trigger, ensure_ascii=False, indent=2)}

## Customer (None if not a customer-scoped message)
{json.dumps(customer, ensure_ascii=False, indent=2) if customer else "null"}

Return JSON with keys: body, cta, send_as, suppression_key, rationale.
- cta: one of "open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"
- send_as: "{send_as}"
- suppression_key: copy from trigger
- rationale: 1-2 sentences on the key design choices made
"""
    # Retry with exponential backoff on 429 quota errors
    for attempt in range(5):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "body":            types.Schema(type=types.Type.STRING),
                            "cta":             types.Schema(type=types.Type.STRING),
                            "send_as":         types.Schema(type=types.Type.STRING),
                            "suppression_key": types.Schema(type=types.Type.STRING),
                            "rationale":       types.Schema(type=types.Type.STRING),
                        },
                        required=["body","cta","send_as","suppression_key","rationale"]
                    ),
                    temperature=0.0,
                )
            )
            return json.loads(resp.text)
        except Exception as e:
            msg = str(e)
            if "429" in msg and attempt < 4:
                wait = 15 * (2 ** attempt)   # 15, 30, 60, 120 s
                print(f"      429 quota — waiting {wait}s before retry {attempt+2}/5")
                time.sleep(wait)
            else:
                raise

def main():
    if not API_KEY:
        print("ERROR: set GEMINI_API_KEY"); sys.exit(1)

    client = genai.Client(api_key=API_KEY)
    cats, merchants, customers, triggers = load_contexts()
    pairs  = load_json(EXPANDED / "test_pairs.json")["pairs"]

    print(f"Loaded {len(cats)} cats, {len(merchants)} merchants, {len(customers)} customers, {len(triggers)} triggers")
    print(f"Generating {len(pairs)} submissions...\n")

    lines = []
    for i, pair in enumerate(pairs, 1):
        tid  = pair["trigger_id"]
        mid  = pair["merchant_id"]
        cid  = pair.get("customer_id")
        tid_ = pair["test_id"]

        trg  = triggers.get(tid)
        mer  = merchants.get(mid)
        cat  = cats.get(mer["category_slug"]) if mer else None
        cus  = customers.get(cid) if cid else None

        if not (trg and mer and cat):
            print(f"  [{tid_}] SKIP — missing context (trg={bool(trg)} mer={bool(mer)} cat={bool(cat)})")
            continue

        try:
            time.sleep(1.0)   # gentle pacing: 1 req/sec well within 15 RPM free limit
            result = compose(client, cat, mer, trg, cus)
            # Post-process: strip any URLs that slipped through
            import re
            result["body"] = re.sub(r'https?://\S+|www\.\S+', '', result["body"]).strip()
            result["test_id"] = tid_
            lines.append(result)
            snippet = result["body"][:80].replace("\n", " ")
            print(f"  [{tid_}] OK  — {snippet}…")
        except Exception as e:
            print(f"  [{tid_}] ERR — {e}")

    out = Path(__file__).parent / "submission.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln, ensure_ascii=False) + "\n")

    print(f"\nDone. {len(lines)}/30 entries written → {out}")

if __name__ == "__main__":
    main()
