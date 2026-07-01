# Provenance Guard

Provenance Guard is a small Flask backend I built for AI201 that looks at a piece of submitted writing and gives an opinion on whether it was written by AI or by a human. It doesn't try to be a perfect detector (nothing really can be), so instead of forcing a yes/no answer it returns a confidence score and, when the evidence is mixed, just says it's not sure. Creators can also appeal a decision they disagree with, and every decision plus every appeal gets written to an audit log so nothing happens silently.

This project went through 5 planning/build milestones (see `planning.md` for the original design doc). This README is the Milestone 6 writeup that documents what actually got built.

## Architecture overview

Here's what happens when someone submits text:

1. A creator sends `POST /submit` with `text` and `creator_id`.
2. `app.py` validates that both fields are there, then generates a random `content_id` for this piece of content.
3. `detector.py` runs the text through two separate signals:
   - a call to a Groq-hosted LLM that judges how AI-like the writing sounds
   - a local stylometric function that scores the text using plain Python text stats (no API call)
4. Those two scores get combined into one `confidence` score, and that score gets mapped to an `attribution` (`likely_ai`, `likely_human`, or `uncertain`).
5. `labels.py` turns the attribution + confidence into the plain-language label a user would actually read.
6. `audit.py` writes the full decision (scores, attribution, label, creator, timestamp) to a JSON audit log on disk.
7. The API responds with the `content_id`, `attribution`, `confidence`, `label`, and both raw signal scores.

If a creator disagrees with the result, they hit `POST /appeal` with the `content_id` and their reasoning. That gets appended to the audit log as its own entry, and the log stays fully readable through `GET /log`.

Every `/submit` call also goes through a rate limiter (`flask-limiter`) before it ever reaches the detection logic, since each submission triggers a real API call to Groq.

## Detection signals

I use two signals instead of one because I didn't want the whole system to rely on a single opinion. If both signals agree, I can be more confident. If they disagree, that disagreement is actually useful information.

### Signal 1: Groq LLM classification

This sends the submitted text to a Groq-hosted model (`llama-3.1-8b-instant`) and asks it to rate how AI-generated the writing looks, based on tone, structure, coherence, and style. It returns a number from 0 to 1 (`llm_score`).

I chose this because an LLM is actually decent at picking up on the "feel" of AI writing — the overly balanced phrasing, the way it wraps everything up neatly, that kind of thing. It's the strongest signal I have, which is why it gets more weight in the final score (more on that below).

**Limitation:** It can misjudge writing that's just naturally polished — think formal academic writing, or writing from someone who isn't a native English speaker and writes very "correctly" as a result. That kind of writing can get flagged even though a real person wrote every word.

### Signal 2: Stylometric heuristics

This one doesn't call any API at all — it's just plain Python looking at surface-level writing statistics:

- **Sentence length variation** — humans tend to naturally vary how long their sentences are; AI text tends to be more even.
- **Vocabulary diversity** — the ratio of unique words to total words. Less variety can lean AI-like.
- **Punctuation variety** — how many different punctuation marks actually show up. AI writing tends to stick to a narrower set.

Each of the three gets turned into a 0–1 score and averaged into one `style_score`.

I chose this because it's fast, free, and looks at something completely different than the LLM signal — actual sentence structure instead of "vibes." It's a good second opinion.

**Limitation:** It really struggles with short text. If someone submits one or two sentences, there isn't enough data to measure sentence length variation or vocabulary diversity in any meaningful way, so the score can end up close to a coin flip. It also doesn't do well with unusual formats like poetry, lists, or very repetitive writing.

## Confidence scoring

The two scores get combined with a weighted average, not a plain 50/50 split:

```python
def combine_scores(llm_score, style_score):
    return 0.6 * llm_score + 0.4 * style_score
```

I weighted the Groq score higher (60%) because in testing, the stylometric score moved around a lot on shorter or more casual submissions and wasn't something I trusted to carry half the decision. The LLM signal was just more consistent, so it gets more say, but the stylometric signal still pulls the result in a different direction when the two disagree.

That combined `confidence` score then maps to an attribution:

| Confidence | Attribution |
|---|---|
| 0.75 and up | `likely_ai` |
| 0.40 – 0.74 | `uncertain` |
| below 0.40 | `likely_human` |

The `uncertain` band is intentionally wide. Telling a real human writer "this looks AI-generated" is a worse mistake than just admitting the system isn't sure, so the threshold for a confident `likely_ai` call is set high on purpose.

## Example submissions

**Example 1 — high confidence**

Text: a generic, formal five-sentence paragraph about time management (the kind of five-paragraph-essay filler that reads very smoothly and says very little).

- `llm_score`: 0.92 — Groq flagged the tone as very generic and "wrapped up too neatly"
- `style_score`: 0.55 — sentence lengths were fairly even and vocabulary was on the plainer side
- `confidence`: `0.6 * 0.92 + 0.4 * 0.55 = 0.77`
- `attribution`: `likely_ai`
- `label`: `"This content is likely AI-generated (77% confidence)."`

**Example 2 — lower confidence**

Text: a short, casual first-person post about a messed-up sleep schedule, written with lowercase letters, slang, and an uneven rhythm.

- `llm_score`: 0.35 — Groq leaned human but wasn't fully certain, since the writing was still coherent
- `style_score`: 0.53 — despite reading as casual, the text was short enough that the stylometric signal didn't have much to work with
- `confidence`: `0.6 * 0.35 + 0.4 * 0.53 = 0.42`
- `attribution`: `uncertain`
- `label`: `"We're not sure whether this content is AI or human (42% confidence)."`

That second example is a good illustration of why the stylometric signal's short-text weakness matters — a clearly casual, human-sounding post still landed in "uncertain" territory instead of confidently "likely human," because there just wasn't enough text for the heuristics to be sure of anything.

## Transparency labels

These are the exact strings `labels.py` returns, with the live confidence percentage filled in:

**Likely AI**
```
This content is likely AI-generated ({confidence}% confidence).
```

**Likely Human**
```
This content is likely human-written ({confidence}% confidence).
```

**Uncertain**
```
We're not sure whether this content is AI or human ({confidence}% confidence).
```

These are written in plain language on purpose — whoever reads this label isn't expected to know what "stylometric" means, they just need a straight answer and a number they can judge for themselves.

## Appeals workflow

If a creator thinks a decision was wrong, they call `POST /appeal` with:

```json
{
  "content_id": "the-id-from-their-original-submission",
  "creator_reasoning": "I wrote this myself, I just edit heavily and use a formal tone."
}
```

That gets logged as its own entry in the audit log with `status: "under_review"`. Nothing about the original submission is deleted or changed — the appeal just sits alongside it. Anyone looking at `GET /log` can see the original scores and label right next to the creator's pushback, so a reviewer never has to guess what happened.

Right now there's no automatic "overturn" logic — an appeal doesn't change the original attribution by itself. It just flags the content for a human to actually look at.

## Rate limiting

`/submit` is limited to **10 requests per minute and 100 per day**, keyed by IP address (`flask-limiter`'s `get_remote_address`).

I picked these specifically because every `/submit` call triggers a real, billed call to the Groq API. Without a limit, someone could accidentally (or on purpose) spam the endpoint and burn through API quota fast. 10 per minute is generous enough for normal manual testing and normal use, but it stops a script from hammering the endpoint in a loop. The 100/day cap is a backstop on top of that, since this is running on a free-tier API key for a class project, not production infrastructure.

`/appeal` and `/log` aren't rate limited, since they don't call an external API and cost nothing to run.

## Audit log

Every decision made by `/submit` and every appeal made through `/appeal` gets appended to `audit_log.json`, a flat JSON file on disk (`audit.py` handles reading/writing it). Each submission entry has the timestamp, content ID, creator ID, both raw scores, the combined confidence, the attribution, and status. Appeal entries record the content ID, the creator's reasoning, and a timestamp.

`GET /log` returns the whole thing as-is. I wanted the audit trail to be something anyone reviewing the system could actually look at directly, instead of just trusting that logging happens somewhere behind the scenes.

## Known limitations

- **Short text breaks the stylometric signal.** A one or two sentence submission doesn't give the heuristics enough to work with, so `style_score` can end up close to random.
- **Heavily AI-edited human writing confuses both signals.** If someone writes a draft themselves and has AI clean up the grammar, the two signals can disagree and land on `uncertain` — the system has no way to explain what actually happened.
- **False positive risk for formal or non-native English writing.** Simple, very correct sentence structure can look uniform to both signals even though a human wrote it.
- **The rate limiter is in-memory** (`storage_uri="memory://"`), so limits reset if the server restarts and wouldn't work correctly if this were ever run across multiple server processes.
- **The audit log is a single local JSON file**, not a database. It's not built to handle concurrent writes safely or to scale past a small class project.
- **`creator_id` isn't authenticated.** Anyone can submit as any `creator_id`, and there's nothing stopping someone from filing an appeal on content that isn't theirs.
- **It's running on Flask's built-in dev server** (`debug=True`), which is explicitly not meant for real production traffic.
- **No automated test suite yet.** Testing so far has been manual `curl`/Postman requests against clearly-AI, clearly-human, and borderline text samples.

## Spec reflection

**How the planning doc helped:** Having the confidence ranges and the exact JSON request/response shapes written out in `planning.md` before I touched any code made the actual implementation a lot smoother. By the time I got to building `app.py` and `labels.py`, I already knew exactly what fields needed to come back in the response and what each confidence range should mean, so I wasn't redesigning things mid-build.

**How the implementation changed from the plan:** The original plan called for a simple average of the two scores (`(groq_score + stylometric_score) / 2`). Once I actually started testing with real text, I found the stylometric score swung around more than I trusted, especially on shorter inputs, so I changed `combine_scores` to weight the Groq signal higher (60/40) instead of a straight 50/50 split.

## How to run it locally

**1. Clone and set up a virtual environment**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Add your Groq API key**

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_groq_api_key_here
```

**3. Run the server**

```bash
python app.py
```

It'll start on `http://127.0.0.1:5000`.

**4. Try it out**

```bash
curl -X POST http://127.0.0.1:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "Some text to check.", "creator_id": "user123"}'
```

```bash
curl -X POST http://127.0.0.1:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "the-id-you-got-back", "creator_reasoning": "I wrote this myself."}'
```

```bash
curl http://127.0.0.1:5000/log
```
