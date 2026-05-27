# Phase 4: Metadata Extraction

Extract optimized SEO metadata from the following blog article.

## Input

- **Main Keyword:** {keyword}
- **Article:**
```markdown
{article}
```

## Metadata Requirements

### SEO Title
- Length: **50-60 characters** (strict).
- The **Main Keyword must be at the very start** of the title.
- Compelling and click-worthy.

### SEO Description
- Length: **150-160 characters** (strict).
- Include the Main Keyword naturally.
- Summarize the article's value proposition.

### H1 Heading
- The primary heading for the article page.
- Should match or closely relate to the SEO title.
- Include the Main Keyword.

### URL Slug
- **Kebab-case** format (lowercase, words separated by hyphens).
- Include the Main Keyword.
- Keep concise (3-6 words).
- No special characters, no trailing hyphens.

## Output Format

Return a JSON object:

```json
{
  "title": "Main Keyword: Rest of compelling title here",
  "description": "A 150-160 character meta description that includes the main keyword and summarizes the article value.",
  "h1": "Main keyword in the primary page heading",
  "url_slug": "main-keyword-rest-of-slug"
}
```
