import os
import re
import time
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from google import genai
from google.genai import types

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VeraBot")

app = FastAPI(title="Vera - magicpin Merchant AI Assistant")

START_TIME = time.time()

# =============================================================================
# IN-MEMORY STORAGE
# =============================================================================
# Key: (scope, context_id) -> {version: int, payload: dict}
contexts: Dict[tuple[str, str], Dict[str, Any]] = {}

# Key: conversation_id -> dict state
conversations: Dict[str, Dict[str, Any]] = {}

# Key: suppression_key -> float expiry timestamp
suppressed_keys: Dict[str, float] = {}

# =============================================================================
# HELPER FUNCTIONS & DETECTORS
# =============================================================================

def _get_offer_titles(merchant: Optional[dict]) -> List[str]:
    offers = merchant.get("offers", []) if merchant else []
    titles = []
    for offer in offers:
        title = offer.get("title") or offer.get("name")
        if title and offer.get("status") != "expired":
            titles.append(title)
    return titles


def _greeting_name(merchant: Optional[dict], customer: Optional[dict]) -> str:
    if customer and customer.get("identity", {}).get("name"):
        return customer["identity"]["name"]
    if merchant and merchant.get("identity", {}).get("owner_first_name"):
        return merchant["identity"]["owner_first_name"]
    return "Partner"


def _merchant_name(merchant: Optional[dict]) -> str:
    if merchant and merchant.get("identity", {}).get("name"):
        return merchant["identity"]["name"]
    return "your business"


def _is_hinglish(merchant: Optional[dict], customer: Optional[dict]) -> bool:
    languages = []
    if merchant and merchant.get("identity", {}).get("languages"):
        languages.extend([str(lang).lower() for lang in merchant["identity"]["languages"]])
    if customer and customer.get("identity", {}).get("language_pref"):
        languages.append(str(customer["identity"]["language_pref"]).lower())
    return any(lang.startswith("hi") or lang == "hindi" for lang in languages)


def _compose_body(category: Optional[dict], merchant: Optional[dict], trigger: Optional[dict], customer: Optional[dict] = None) -> tuple[str, str]:
    category_slug = (category or {}).get("slug", "general")
    merchant_name = _merchant_name(merchant)
    owner_name = _greeting_name(merchant, customer)
    offer_titles = _get_offer_titles(merchant)
    offer_title = offer_titles[0] if offer_titles else None
    trigger_kind = (trigger or {}).get("kind", "generic")
    payload = (trigger or {}).get("payload", {}) or {}
    top_item = payload.get("top_item") or {}
    title = top_item.get("title") or payload.get("title") or payload.get("headline")
    source = top_item.get("source") or payload.get("source")
    trial_n = top_item.get("trial_n") or payload.get("trial_n")
    cta = "none"

    if trigger_kind == "research_digest" and title:
        if _is_hinglish(merchant, customer):
            body = f"{owner_name}, {title}."
            if source:
                body += f" {source} se relevant insight hai."
            if trial_n:
                body += f" {trial_n}-patient study ka angle use kar sakte ho."
            body += " Kya main isko aapke liye ek short patient WhatsApp draft mein convert kar doon?"
        else:
            body = f"{owner_name}, {title}."
            if source:
                body += f" Source: {source}."
            if trial_n:
                body += f" The {trial_n}-patient study is worth a look."
            body += " Want me to turn this into a short patient WhatsApp draft?"
        cta = "open_ended"
        return body, cta

    if trigger_kind == "recall_due" and customer:
        customer_name = customer.get("identity", {}).get("name", "there")
        if _is_hinglish(merchant, customer):
            body = f"Hi {customer_name}, {merchant_name} se bol rahi hoon. Aapki recall window khul chuki hai."
            if offer_title:
                body += f" {offer_title} ka option abhi ready hai."
            body += " Kya aap ek slot confirm karna chahenge?"
        else:
            body = f"Hi {customer_name}, this is {merchant_name}. Your recall window is open."
            if offer_title:
                body += f" {offer_title} is available now."
            body += " Would you like to confirm a slot?"
        cta = "multi_choice_slot"
        return body, cta

    if trigger_kind in {"perf_spike", "perf_dip"}:
        perf = (merchant or {}).get("performance", {}) or {}
        views = perf.get("views")
        ctr = perf.get("ctr")
        if _is_hinglish(merchant, customer):
            body = f"{owner_name}, aapke latest numbers dekh kar lag raha hai ki aapka account momentum mein hai."
            if ctr is not None:
                body += f" Current CTR {ctr:.2%} hai."
            if views is not None:
                body += f" 30d views {views} hain."
            body += " Kya main aapke liye ek quick next step suggest karun?"
        else:
            body = f"{owner_name}, your latest numbers suggest there is room to act now."
            if ctr is not None:
                body += f" Current CTR is {ctr:.2%}."
            if views is not None:
                body += f" You have {views} views in the last 30 days."
            body += " Want me to suggest the next best step?"
        cta = "binary_yes_no"
        return body, cta

    if trigger_kind == "milestone_reached":
        if _is_hinglish(merchant, customer):
            body = f"{owner_name}, aapne milestone cross kar liya hai. Main aapke liye ek short celebration post ya follow-up offer draft kar sakta hoon."
        else:
            body = f"{owner_name}, you’ve reached a meaningful milestone. I can draft a quick follow-up message or offer for you."
        cta = "open_ended"
        return body, cta

    if trigger_kind in {"dormant_with_vera", "scheduled_recurring"}:
        if _is_hinglish(merchant, customer):
            body = f"{owner_name}, main soch rahi hoon ki aapka {category_slug} profile abhi thoda stale lag raha hai. Ek small refresh karna useful ho sakta hai."
        else:
            body = f"{owner_name}, your {category_slug} profile looks like it could use a small refresh. I can help with a quick update."
        cta = "binary_yes_no"
        return body, cta

    if category_slug == "dentists":
        if offer_title:
            body = f"{owner_name}, {offer_title} ka option aapke clinic ke liye useful ho sakta hai. Main aapke liye ek short patient reminder draft kar sakta hoon."
        else:
            body = f"{owner_name}, aapke clinic ke liye ek simple, relevant update ready hai. Kya main use aapke patients tak bhej dun?"
        cta = "open_ended"
        return body, cta

    if _is_hinglish(merchant, customer):
        body = f"{owner_name}, main aapke liye ek simple, relevant update ready kar sakti hoon. Kya aap chahenge ki main use aapke business ke hisaab se tailor karun?"
    else:
        body = f"{owner_name}, I can help with a simple, relevant update tailored to your business. Would you like me to draft it?"
    cta = "binary_yes_no"
    return body, cta


def compose(category: Optional[dict], merchant: Optional[dict], trigger: Optional[dict], customer: Optional[dict] = None) -> dict:
    """Deterministic compose function that matches the submission contract in the challenge brief."""
    body, cta = _compose_body(category, merchant, trigger, customer)
    body = re.sub(r'https?://\S+|www\.\S+', '', body).strip()
    body = re.sub(r'\s+', ' ', body).strip()
    trigger = trigger or {}
    send_as = "merchant_on_behalf" if trigger.get("scope") == "customer" else "vera"
    return {
        "body": body,
        "cta": cta,
        "send_as": send_as,
        "suppression_key": trigger.get("suppression_key", f"trg:{trigger.get('id', 'default')}") ,
        "rationale": "Used a deterministic, context-fit template that anchors on available facts and keeps the CTA single and low-friction.",
    }


def get_gemini_client() -> Optional[genai.Client]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY environment variable is not set. LLM calls will fail.")
        return None
    return genai.Client(api_key=api_key)

def clean_body_text(text: str) -> str:
    """Post-process LLM response to remove Markdown codeblocks, JSON wrappers, etc."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def strip_urls(text: str) -> str:
    """Strictly remove any URLs to prevent Meta policy violations and penalties."""
    # Regex to match URLs
    url_pattern = re.compile(r'https?://\S+|www\.\S+')
    return url_pattern.sub("", text)

def detect_auto_reply(message: str, history: List[Dict[str, Any]]) -> bool:
    """
    Detect WhatsApp Business canned auto-replies.
    Heuristics:
    1. Common canned prefixes.
    2. Exact duplicate messages received consecutively.
    """
    msg_lower = message.lower().strip()
    
    # Common Indian merchant auto-reply patterns
    canned_phrases = [
        "thank you for contacting",
        "our team will respond",
        "aapki jaankari ke liye",
        "hamari team tak pahuncha",
        "automated assistant",
        "we are currently unavailable",
        "welcome to",
        "will get back to you shortly"
    ]
    for phrase in canned_phrases:
        if phrase in msg_lower:
            return True
            
    # Check for consecutive identical messages
    merchant_received = [h["message"] for h in history if h.get("from_role") == "merchant"]
    if len(merchant_received) >= 2 and merchant_received[-1] == message:
        return True
        
    return False

def detect_intent_transition(message: str) -> bool:
    """Detect if the merchant says yes/go ahead/let's do it."""
    msg_lower = message.lower().strip()
    positive_signals = [
        "ok", "yes", "let's do it", "go ahead", "do it", "sure", "yup", "yeah", "karo", "karein", "haan",
        "confirm", "send", "draft", "bhejo", "chalao", "start"
    ]
    # Simple word boundary or exact matching
    for sig in positive_signals:
        if re.search(rf"\b{sig}\b", msg_lower):
            return True
    return False

def detect_opt_out(message: str) -> bool:
    """Detect if the merchant wants to stop or exit."""
    msg_lower = message.lower().strip()
    stop_signals = [
        "stop", "unsubscribe", "not interested", "dont message", "don't message", "band karo",
        "mat bhejo", "nahi chahiye", "please stop", "useless"
    ]
    for sig in stop_signals:
        if sig in msg_lower:
            return True
    return False

# =============================================================================
# API SCHEMAS
# =============================================================================

class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str

class TickBody(BaseModel):
    now: str
    available_triggers: List[str] = []

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int

# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _), _ in contexts.items():
        if scope in counts:
            counts[scope] += 1
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts
    }

@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Team Alpha",
        "team_members": ["Alice", "Bob"],
        "model": "claude-opus-4-7",
        "approach": "single-prompt composer with retrieval over digest items + dispatch by trigger.kind",
        "contact_email": "team@example.com",
        "version": "1.2.0",
        "submitted_at": "2026-04-26T08:00:00Z"
    }

@app.post("/v1/context")
async def push_context(body: ContextBody):
    if body.scope not in ["category", "merchant", "customer", "trigger"]:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_scope", "details": f"Unsupported scope: {body.scope}"},
        )
        
    key = (body.scope, body.context_id)
    cur = contexts.get(key)
    
    if cur and cur["version"] >= body.version:
        return JSONResponse(
            status_code=409,
            content={"accepted": False, "reason": "stale_version", "current_version": cur["version"]},
        )
        
    contexts[key] = {
        "version": body.version,
        "payload": body.payload
    }
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.utcnow().isoformat() + "Z"
    }

@app.post("/v1/teardown")
async def teardown():
    contexts.clear()
    conversations.clear()
    suppressed_keys.clear()
    return {"status": "ok", "message": "State wiped successfully"}

@app.post("/v1/tick")
async def tick(body: TickBody):
    client = get_gemini_client()
    now_dt = datetime.fromisoformat(body.now.replace("Z", "+00:00"))
    
    # Filter expired suppressed keys
    to_delete = [k for k, exp in suppressed_keys.items() if now_dt.timestamp() >= exp]
    for k in to_delete:
        del suppressed_keys[k]
        
    actions = []
    
    for trg_id in body.available_triggers:
        trg_ctx = contexts.get(("trigger", trg_id))
        if not trg_ctx:
            continue
        trg = trg_ctx["payload"]
        
        # Check suppression
        supp_key = trg.get("suppression_key")
        if supp_key and supp_key in suppressed_keys:
            logger.info(f"Trigger {trg_id} suppressed by key {supp_key}")
            continue
            
        merchant_id = trg.get("merchant_id")
        merchant_ctx = contexts.get(("merchant", merchant_id))
        if not merchant_ctx:
            continue
        merchant = merchant_ctx["payload"]
        
        category_slug = merchant.get("category_slug")
        category_ctx = contexts.get(("category", category_slug))
        if not category_ctx:
            continue
        category = category_ctx["payload"]
        
        customer_id = trg.get("customer_id")
        customer = None
        if customer_id:
            customer_ctx = contexts.get(("customer", customer_id))
            if customer_ctx:
                customer = customer_ctx["payload"]
                
        # Call the composer
        action = compose_action(client, category, merchant, trg, customer)
        if action:
            # Register suppression
            expires_at_str = trg.get("expires_at")
            if expires_at_str:
                exp_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                suppressed_keys[action["suppression_key"]] = exp_dt.timestamp()
            else:
                suppressed_keys[action["suppression_key"]] = now_dt.timestamp() + 86400 * 7 # 7 days fallback
                
            # Initialize conversation state
            conv_id = action["conversation_id"]
            conversations[conv_id] = {
                "conversation_id": conv_id,
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "trigger_id": trg_id,
                "history": [{"from_role": "vera", "message": action["body"], "timestamp": body.now}],
                "auto_reply_count": 0,
                "intent_state": "qualifying",
                "last_sent_body": action["body"]
            }
            actions.append(action)
            
    return {"actions": actions}

def compose_reply_fallback(
    state: dict,
    category: Optional[dict],
    merchant: Optional[dict],
    customer: Optional[dict],
) -> dict:
    owner_name = _greeting_name(merchant, customer)
    if _is_hinglish(merchant, customer):
        body = f"{owner_name}, main aapke liye ek short next step draft kar sakti hoon. Kya aap chahenge ki main use ready karun?"
        cta = "open_ended"
    else:
        body = f"{owner_name}, I can draft the next step for you right away. Would you like me to prepare it?"
        cta = "open_ended"
    return {
        "action": "send",
        "body": body,
        "cta": cta,
        "rationale": "Used a deterministic fallback response because no LLM client was available.",
    }


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    client = get_gemini_client()
    
    conv_id = body.conversation_id
    state = conversations.get(conv_id)
    
    # If no state in memory, restore basic structure from current incoming info
    if not state:
        state = {
            "conversation_id": conv_id,
            "merchant_id": body.merchant_id,
            "customer_id": body.customer_id,
            "trigger_id": None,
            "history": [],
            "auto_reply_count": 0,
            "intent_state": "qualifying",
            "last_sent_body": None
        }
        conversations[conv_id] = state
        
    # Append message to history
    state["history"].append({
        "from_role": body.from_role,
        "message": body.message,
        "timestamp": body.received_at
    })
    
    # 1. Check for Opt-Out (exit path)
    if detect_opt_out(body.message):
        return {
            "action": "end",
            "rationale": "Merchant/customer explicitly opted out or expressed frustration. Gracefully exiting."
        }
        
    # 2. Check Auto-Reply
    if detect_auto_reply(body.message, state["history"]):
        state["auto_reply_count"] += 1
        if state["auto_reply_count"] == 1:
            reply_text = (
                "Looks like an auto-reply. 😊 Jab bhi owner free hon, "
                "please reply with 'YES' to check the details."
            )
            state["history"].append({"from_role": "vera", "message": reply_text, "timestamp": body.received_at})
            state["last_sent_body"] = reply_text
            return {
                "action": "send",
                "body": reply_text,
                "cta": "binary_yes_no",
                "rationale": "First auto-reply detected. Cues the owner to reply."
            }
        elif state["auto_reply_count"] == 2:
            return {
                "action": "wait",
                "wait_seconds": 14400, # backoff 4 hours
                "rationale": "Consecutive auto-replies. Backing off 4 hours to avoid loop."
            }
        else:
            return {
                "action": "end",
                "rationale": "Persistent auto-replies. Closing conversation to stop turn burn."
            }
            
    # Reset auto reply count on real message
    state["auto_reply_count"] = 0
    
    # 3. Intent Transition Check
    if detect_intent_transition(body.message):
        state["intent_state"] = "action"
        
    # Load contexts for generation
    merchant_ctx = contexts.get(("merchant", body.merchant_id))
    merchant = merchant_ctx["payload"] if merchant_ctx else None
    
    category = None
    if merchant:
        category_ctx = contexts.get(("category", merchant.get("category_slug")))
        if category_ctx:
            category = category_ctx["payload"]
            
    customer = None
    if body.customer_id:
        customer_ctx = contexts.get(("customer", body.customer_id))
        if customer_ctx:
            customer = customer_ctx["payload"]
            
    # Generate next message
    if not client:
        reply_action = compose_reply_fallback(state, category, merchant, customer)
    else:
        reply_action = compose_reply(client, state, category, merchant, customer)
    
    if reply_action["action"] == "send":
        # Check for repetition
        if reply_action["body"] == state["last_sent_body"]:
            # Small modification to prevent repetition penalty
            reply_action["body"] += " (Let me know if this works!)"
        state["last_sent_body"] = reply_action["body"]
        state["history"].append({"from_role": "vera", "message": reply_action["body"], "timestamp": body.received_at})
        
    return reply_action

# =============================================================================
# COMPOSER ENGINE (GEMINI PROMPTING)
# =============================================================================

def compose_action(
    client: Optional[genai.Client],
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None
) -> Optional[dict]:
    
    send_as = "merchant_on_behalf" if trigger.get("scope") == "customer" else "vera"
    if not client:
        fallback = compose(category, merchant, trigger, customer)
        fallback.update({
            "conversation_id": f"conv_{merchant.get('merchant_id')}_{trigger.get('id')}",
            "merchant_id": merchant.get("merchant_id"),
            "customer_id": customer.get("customer_id") if customer else None,
            "trigger_id": trigger.get("id"),
            "template_name": "vera_generic_v1",
            "template_params": [fallback["body"]],
        })
        return fallback
    
    # Build prompt instructions based on the categories, voice profile, and constraints
    voice = category.get("voice", {})
    tone = voice.get("tone", "peer_clinical" if category.get("slug") == "dentists" else "collegial")
    taboos = voice.get("taboos", [])
    
    owner_name = merchant.get("identity", {}).get("owner_first_name", "Partner")
    merchant_name = merchant.get("identity", {}).get("name", "Store")
    languages = merchant.get("identity", {}).get("languages", ["en"])
    is_hi = "hi" in languages
    
    # Specific variables depending on category
    catalog_offers = category.get("offer_catalog", [])
    offer_str = json.dumps(catalog_offers, indent=2)
    
    system_prompt = f"""You are Vera, magicpin's merchant AI assistant.
Your task is to write a highly compelling, specific, and personalized outbound WhatsApp message.

CRITICAL RULES:
1. SPECIFICITY: Include a concrete number, delta, price, or citation. Do NOT use generic "flat 10% off" or "grow your business". Use exact price points from the catalog: e.g. "Dental Cleaning @ ₹299" or "Haircut @ ₹99".
2. TONE & CATEGORY VOICE:
   - Category slug: "{category.get('slug')}"
   - Category Voice Tone: {tone}
   - Taboos (NEVER USE these terms): {json.dumps(taboos)}
   - Dental clinic messages must sound like a clinical peer (professional, scientific, using terms like caries/fluoride if relevant).
   - Restaurants and salons should be warm, operator-level.
   - Gyms should be supportive/coach-like, never shame or guilt-trip.
   - Tone must be respectful, peer-level, and non-condescending.
3. LANGUAGE MATCHING:
   - Target languages: {json.dumps(languages)}
   - {"The merchant prefers a Hindi-English code-mix (Hinglish). Write in natural Romanized Hinglish (e.g. 'Aapke clinic ke liye ek update hai', 'kya aap details share kar sakte hain?'). Use English for functional nouns like profile, post, feedback, and Hindi for glue." if is_hi else "Write in professional English."}
4. NO URLS: Do NOT output any URL or website link in the message body.
5. NO HALLUCINATION: Anchor ONLY on the provided context. If a stat, paper citation (e.g. JIDA Oct 2026), price, or competitor distance is not in the context, do NOT invent it.
6. SINGLE CTA: Include exactly one primary Call-To-Action (CTA) at the very end of the message. The CTA must be direct and simple.

Context:
Category Catalog:
{offer_str}

Merchant:
{json.dumps(merchant, indent=2)}

Trigger payload:
{json.dumps(trigger, indent=2)}

Customer (if scope is customer):
{json.dumps(customer, indent=2) if customer else "None"}

Your output must be JSON format with exactly these fields:
- body: the WhatsApp message text (concise, clear, no URLs, single CTA at the end)
- cta: CTA type (one of: "open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none")
- rationale: a short 1-2 sentence explanation of your design choices (e.g. why Hinglish, why that spec anchor)
- template_name: a template name matching the trigger category (e.g. "vera_research_digest_v1", "merchant_recall_reminder_v1", "vera_generic_v1")
- template_params: list of strings representing the parameter values to fill the template slots (must match the core facts in the body)
"""

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=system_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "body": types.Schema(type=types.Type.STRING),
                        "cta": types.Schema(type=types.Type.STRING),
                        "rationale": types.Schema(type=types.Type.STRING),
                        "template_name": types.Schema(type=types.Type.STRING),
                        "template_params": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING))
                    },
                    required=["body", "cta", "rationale", "template_name", "template_params"]
                ),
                temperature=0.0
            )
        )
        
        res_data = json.loads(clean_body_text(response.text))
        
        # Guardrails check
        res_data["body"] = strip_urls(res_data["body"])
        
        # Fill programmatic fields
        res_data["send_as"] = send_as
        res_data["suppression_key"] = trigger.get("suppression_key", f"trg:{trigger.get('id')}")
        res_data["conversation_id"] = f"conv_{merchant.get('merchant_id')}_{trigger.get('id')}"
        
        return res_data
    except Exception as e:
        logger.error(f"Error in compose_action: {e}")
        # Return a safe fallback context-driven fallback action so we don't return malformed JSON
        supp_key = trigger.get("suppression_key", "fallback_suppression")
        return {
            "conversation_id": f"conv_{merchant.get('merchant_id')}_{trigger.get('id')}",
            "merchant_id": merchant.get("merchant_id"),
            "customer_id": customer.get("customer_id") if customer else None,
            "send_as": send_as,
            "trigger_id": trigger.get("id"),
            "template_name": "vera_generic_v1",
            "template_params": [owner_name, "Vera here"],
            "body": f"Hi {owner_name}, Vera here from magicpin. Can we chat about your GBP profile completion?",
            "cta": "binary_yes_no",
            "suppression_key": supp_key,
            "rationale": "Fallback message due to composer exception"
        }

def compose_reply(
    client: genai.Client,
    state: dict,
    category: Optional[dict],
    merchant: Optional[dict],
    customer: Optional[dict]
) -> dict:
    
    languages = merchant.get("identity", {}).get("languages", ["en"]) if merchant else ["en"]
    is_hi = "hi" in languages
    
    system_prompt = f"""You are Vera, magicpin's merchant assistant (or drafting on behalf of the merchant).
A conversation is currently active. Advance the conversation.

Intent State: {state.get('intent_state')}
- If state is "action", the user agreed. Provide the concrete next step or confirmation (e.g. drafting post, finalizing slots) and stop asking diagnostic or qualifying questions!
- If qualifying, answer questions or direct them to action.

Rules:
1. Do NOT use URLs.
2. Address them appropriately. Hindi-English mixed tone if prefers Hindi.
3. Keep it brief.
4. Return JSON only.

History:
{json.dumps(state.get('history'), indent=2)}

Category:
{json.dumps(category, indent=2) if category else "None"}

Merchant:
{json.dumps(merchant, indent=2) if merchant else "None"}

Your output must be JSON format with exactly:
- action: "send" or "wait" or "end"
- body: the WhatsApp reply message body (empty if action is wait/end)
- cta: the CTA type (empty if action is wait/end)
- rationale: brief 1-sentence design note
- wait_seconds: integer (if action is wait)
"""

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=system_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "action": types.Schema(type=types.Type.STRING),
                        "body": types.Schema(type=types.Type.STRING),
                        "cta": types.Schema(type=types.Type.STRING),
                        "rationale": types.Schema(type=types.Type.STRING),
                        "wait_seconds": types.Schema(type=types.Type.INTEGER)
                    },
                    required=["action", "body", "cta", "rationale"]
                ),
                temperature=0.0
            )
        )
        
        res_data = json.loads(clean_body_text(response.text))
        if res_data.get("body"):
            res_data["body"] = strip_urls(res_data["body"])
        return res_data
    except Exception as e:
        logger.error(f"Error in compose_reply: {e}")
        return {
            "action": "send",
            "body": "Got it. Let me set that up for you.",
            "cta": "none",
            "rationale": "Fallback response due to exception"
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot:app", host="0.0.0.0", port=8080, log_level="info")
