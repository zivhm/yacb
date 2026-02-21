---
name: web-search
description: Search the web with Tavily for current information, news, and images.
---

# Web Search

Search the web using the `web_search` tool powered by Tavily.

## Basic search

```
web_search query="latest news about SpaceX"
```

## Include images

When the user asks for pictures or images, use `include_images`:

```
web_search query="purple doll" include_images=true
```

Images are returned as URLs at the end of the results. Share them directly with the user.

## News search

For current events or time-sensitive topics, use `topic="news"`:

```
web_search query="stock market today" topic="news"
```

## Tips

- Keep queries concise and specific — Tavily works best with natural language questions
- Use `include_images=true` whenever the user asks to "look up", "find a picture of", or "show me" something
- Use `topic="news"` for breaking news, current events, sports scores, recent announcements
- Default result count is 5, increase with `count` for broader searches
- If the first search doesn't find what you need, rephrase rather than repeating the same query
