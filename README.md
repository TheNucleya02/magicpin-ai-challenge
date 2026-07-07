# magicpin Vera AI Assistant - Submission README

## 1. Approach
Our approach leverages a modular FastAPI architecture decoupled from the LLM provider, utilizing Google's `gemini-2.5-flash` model. 

Key architectural components include:
* **In-Memory Context Store**: Fast, thread-safe, versioned context repository supporting atomic replacements.
* **Auto-Reply Filter**: Layered heuristics (string checks + sequence counts) to block looping WhatsApp canned responses.
* **Hinglish Style Router**: Dynamic generation rules switching between formal English and Hinglish (Romanized Hindi) based on the merchant's context languages.
* **Intent-Handoff State Tracker**: An in-memory conversation state machine tracking transition flags like "yes" or "confirm" to instantly switch the model from qualifying to execution mode.

## 2. Tradeoffs Made
* **Local In-Memory Cache vs Redis**: For the scale of this test, we prioritized low latency and zero external service dependencies by storing contexts in thread-safe dictionaries rather than introducing Redis/SQLite overhead.
* **Regex/Heuristics for Intent and Auto-Reply vs LLM Classifier**: We used deterministic string matching for initial triage of opt-out, yes/no signals, and canned replies. This ensures sub-second latency for these critical routing tasks, using the LLM strictly for content synthesis.

## 3. What Additional Context Would Have Helped Most
* **Canonical Test-Pair Reference**: Having the list of 30 test pairs pre-defined in the initial brief would have allowed static validation of generated outputs without running the generator script first.
* **Strict URL Spec Consistency**: Resolving the mismatch between the allowed URL guideline in the product brief and the hard failure penalty in the testing harness earlier. We opted for a strict URL-removal strategy to prevent penalty risks.
