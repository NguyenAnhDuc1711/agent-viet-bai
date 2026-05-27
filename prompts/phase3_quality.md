# Phase 3: Quality Gate

Score the following blog article across 5 quality categories.

## Input

- **Main Keyword:** {keyword}
- **Article:**
```markdown
{article}
```
- **Research & Strategy Reference:**
```json
{research_output}
```

## Scoring Categories

Score each category on the specified scale:

### 1. Content (max 30 points)
- Answer-first opening per H2 (40-60 words)
- Main content proportion > 90% of total
- Information depth and originality
- Narrative flow and storytelling quality
- Content fidelity (if title mentions a number, that many items exist)

### 2. SEO (max 25 points)
- Main Keyword in title (at the start), sapo, and 2-3 H2s
- Sub-Keywords distributed in H2s and H3s
- Sentence case headings
- Proper heading hierarchy (H1 > H2 > H3)
- No keyword stuffing

### 3. E-E-A-T (max 15 points)
- Experience signals (first-hand insights, practical examples)
- Expertise markers (deep domain knowledge)
- Authority indicators (data references, expert quotes)
- Trust signals (balanced perspective, cited sources)

### 4. Technical (max 15 points)
- Image Asset Boxes present for every H2 and H3
- No em-dashes (use hyphens)
- No specific year mentions (evergreen)
- Sapo under 100 characters with Main Keyword
- Visual density (no 400+ word sections without images)

### 5. AI Citation Readiness (max 15 points)
- Key Takeaways / summary box presence
- Clear, quotable answer paragraphs
- Structured data-friendly formatting
- FAQ-ready content sections

## Quality Gates

The article PASSES only if BOTH conditions are met:
1. **Total score >= 70** (out of 100)
2. **Each category >= 50% of its max:**
   - Content >= 15
   - SEO >= 12.5
   - E-E-A-T >= 7.5
   - Technical >= 7.5
   - AI Citation >= 7.5

## Output Format

Return a JSON object:

```json
{
  "scores": {
    "content": 0,
    "seo": 0,
    "eeat": 0,
    "technical": 0,
    "ai_citation": 0
  },
  "total": 0,
  "passed": true,
  "feedback": "Detailed feedback on what to improve if the article did not pass. Empty string if passed."
}
```
