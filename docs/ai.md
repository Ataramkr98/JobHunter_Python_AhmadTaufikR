# Job matching and Groq explanations

**AI job matches** ranks active jobs against the signed-in user's resume using
TF-IDF and cosine similarity. The job detail page uses the same active corpus,
so its score agrees with the shortlist. Scores describe text similarity, not
hiring probabilities. The low-memory `stdlib` backend remains supported.

When enabled, Groq explains the top match on `/resume/matches` and the individual
role on `/jobs/<id>`. The pages also show matched skills and requirements not
listed. The model never changes scores or ranking. The anonymous `/api/match`
endpoint does not trigger paid model calls.

Configure the server environment or the ignored local `.env`:

```dotenv
AI_BASE_URL=https://api.groq.com/openai/v1
AI_API_KEY=<your Groq API key>
AI_MODEL_DEFAULT=openai/gpt-oss-20b
AI_MODEL_ANALYZE=openai/gpt-oss-20b
AI_EXPLAIN_MATCHES=true
AI_TIMEOUT_SECONDS=12
AI_MAX_RETRIES=1
AI_CACHE_SECONDS=900
```

`GROQ_API_KEY` can substitute for `AI_API_KEY`. Model selection uses the feature
override, then `AI_MODEL_CHAT`, then `AI_MODEL_DEFAULT`. Confirm model availability
with your account's Groq `/models` endpoint before changing it.

The prompt uses job/profile text and the computed skill breakdown. Structured
contact fields and names are not added to it. User-supplied text is treated as
data. Output is validated as a JSON object and rendered with HTML escaping.

Successful requests are cached for 15 minutes, with at most 256 entries per
worker. Input, provider, credential or model changes invalidate the cache key.
Transient HTTP errors are retried once by default. Failures back off for 30
seconds, and pages continue showing scores and matches with an availability
message. Secrets and upstream response bodies are never logged.

Provider references: [Groq compatibility](https://console.groq.com/docs/openai),
[models](https://console.groq.com/docs/models).
