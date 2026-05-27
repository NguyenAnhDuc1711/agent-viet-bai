# Phase 1: Research & Strategy

You are conducting deep SERP and intent research for a blog article.

## Input

- **Main Keyword:** {keyword}
- **Sub-Keywords:** {sub_keyword}
- **User-Provided Outline (if any):** {outline}

## Your Tasks

### 1. Keyword Logic
- The **first keyword** above is the Main Keyword. All others are Sub-Keywords.
- The Main Keyword must appear in the Title (at the start), Sapo, and 2-3 H2 headings.
- Sub-Keywords should be distributed naturally across H2s and H3s.

### 2. Search Intent & Competitor Analysis
- Classify the search intent (informational, transactional, navigational, commercial).
- Identify the User Goal (what problem does the searcher want solved?).
- Identify 3-5 Information Gaps that competitors miss.

### 3. Keyword Mapping
- Map the Main Keyword and each Sub-Keyword to specific heading positions (H1, H2, H3).
- Ensure natural placement without keyword stuffing.

### 4. Outline Generation (AIDA Framework)
- **Attention:** Hook/introduction section with Main Keyword.
- **Interest:** Core value sections (these form 90%+ of the article).
- **Desire:** Expert insights, case studies, deeper analysis.
- **Action:** Conclusion with actionable takeaways.
- Every H2 and H3 must include a planned image asset.
- If the user provided an outline, you MUST preserve ALL of their headings in your output. You may add additional headings but never remove user-provided ones.

### 5. Visual Asset Planning
- Plan a Cover Image.
- Plan inline images for EVERY major heading (H2 and H3).
- No section should exceed 400-500 words without a visual break.

### 6. Evergreen Content Rules
- Do NOT mention specific years (e.g., 2025, 2026). Use "current trends" or "latest research."

## Output Format

Return a JSON object with this structure:

```json
{
  "strategy": {
    "search_intent": "informational|transactional|navigational|commercial",
    "user_goal": "Description of what the searcher wants",
    "information_gaps": ["gap1", "gap2", "gap3"],
    "target_word_count": 2000,
    "data_points": ["stat1", "stat2", "stat3"]
  },
  "outline": [
    {
      "level": "h2",
      "heading": "Heading text in sentence case",
      "keyword_target": "keyword placed here",
      "image_planned": true,
      "subsections": [
        {
          "level": "h3",
          "heading": "Subheading text",
          "keyword_target": "sub-keyword",
          "image_planned": true
        }
      ]
    }
  ],
  "keyword_map": {
    "main_keyword": "keyword",
    "placement": {
      "title": true,
      "sapo": true,
      "h2_headings": ["heading1", "heading2"],
      "h3_headings": ["heading3"]
    },
    "sub_keywords": {
      "sub_kw_1": ["h2: heading", "h3: heading"]
    }
  },
  "visual_plan": [
    {
      "position": "cover",
      "slug": "cover-image-slug",
      "alt_text": "Descriptive alt text with keywords",
      "gemini_prompt": "Detailed image generation prompt"
    }
  ]
}
```
