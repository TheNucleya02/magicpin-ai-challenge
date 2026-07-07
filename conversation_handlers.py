import os
import json
import logging
from google import genai
from google.genai import types

from bot import compose

logger = logging.getLogger("ConversationHandler")

def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)

def clean_body_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def respond(state: dict, merchant_message: str) -> dict:
    """
    Evaluator hook for multi-turn conversational testing.
    Given current conversation state + latest message, produce the reply.
    """
    client = get_gemini_client()
    if not client:
        return {
            "action": "send",
            "body": "Thanks — I can help with a simple next step for you.",
            "cta": "open_ended",
            "rationale": "No LLM client key configured, so the handler used a deterministic fallback response."
        }

    # Normalize state history if not already formatted
    history = state.get("history", [])
    history.append({
        "from_role": "merchant",
        "message": merchant_message
    })

    system_prompt = f"""You are Vera, magicpin's merchant assistant.
A conversation is currently active. Advance the conversation.

Rules:
1. Do NOT use URLs.
2. Keep it brief.
3. Return JSON only.

History:
{json.dumps(history, indent=2)}

Your output must be JSON format with exactly:
- action: "send" or "wait" or "end"
- body: the WhatsApp reply message body (empty if action is wait/end)
- cta: the CTA type ("open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none")
- rationale: brief 1-sentence design note
- wait_seconds: integer (if action is wait)
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
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
        return json.loads(clean_body_text(response.text))
    except Exception as e:
        logger.error(f"Error in multi-turn handler respond: {e}")
        return {
            "action": "send",
            "body": "Got it. Let me look into that for you.",
            "cta": "none",
            "rationale": "Fallback response due to exception"
        }
