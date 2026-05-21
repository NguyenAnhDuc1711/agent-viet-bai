---
name: gemini-blog-write
description: >
  Write new blog articles from scratch optimized for Google rankings and AI
  citations. Generates full articles with template selection, answer-first
  formatting, Key Takeaways summary box, information gain markers, citation capsules,
  engaging expert insights, Pixabay/Unsplash images, FAQ schema,
  internal linking zones, and proper heading hierarchy. Supports MDX, markdown,
  and HTML output.
  Use when user says "write blog", "new blog post", "create article",
  "write about", "draft blog", "generate blog post".
---

# Blog Writer -- New Article Generation

Writes complete blog articles from a topic, brief, or outline. Every article
follows the 6 pillars of dual optimization (Google rankings + AI citations) and
high-authority SEO standards with an engaging, narrative-driven tone.

**Key references:**
- `references/content-templates.md` - Template selection guide and usage
- `references/quality-scoring.md` - 5-category scoring (Content 30, SEO 25, E-E-A-T 15, Technical 15, AI Citation 15)
- `references/eeat-signals.md` - Experience, expertise, authority, trust markers
- `references/internal-linking.md` - Linking strategy and anchor text rules
- `references/visual-media.md` - Image sourcing and chart styling

## Workflow

### Phase 1: Topic & Keyword Understanding

1. **Keyword Logic:** If multiple keywords are provided, the **first keyword is the Main Keyword**. All subsequent keywords are **Sub-Keywords**.
2. **Clarify the topic:**
   - Target audience
   - Main Keyword (from the first provided term)
   - Sub-Keywords (from the rest)
   - Desired word count (default 2,000+)
   - Platform/format

### Phase 2: Deep SERP & Intent Research (Mandatory)

1. **Competitor Analysis:** Identify "Information Gaps."
2. **Search Intent:** Clearly classify the intent and User Goal.
3. **Keyword Mapping:** Place the **Main Keyword** in the Title (at the start), Sapo, and 2-3 H2s. Distribute **Sub-Keywords** naturally throughout H2s and H3s.
4. **Find 3-5 High-Impact Data Points:** Use data sparingly to validate points.
5. **Visual Asset Planning (Visual Rhythm):**
   - Plan a **Cover Image**.
   - Plan **Inline Images for EVERY major heading (H2 and H3)**. 
   - Rule: No section of text should exceed 400-500 words without a visual break.
   - Every image gets a **Gemini-optimized prompt** (800px width).

### Phase 3: AIDA Outline Generation

Create a structured outline based on the **AIDA** (Attention, Interest, Desire, Action) framework. 

**Golden Rules:**
- **Visual Density:** Every H2 and every H3 subsection **must** include a visible **Image Asset Box** placed immediately after the heading.
- **Narrative Focus:** Focus on storytelling and expert observation. Minimize statistics.
- **Main Content Proportion:** Main Content (Interest + Desire sections) must exceed **90%** of the total article length.
- **Content Fidelity:** If the title mentions a specific number, you **must** provide exactly that many items.
- **Evergreen Content:** **Do not mention specific years** (e.g., 2025, 2026). Use "current trends" or "latest research."

### Phase 5: Content Writing (High-Authority Narrative)

Use a professional, objective, yet engaging voice. **All content must be in English.** 

#### 5a. Metadata & Frontmatter
- **SEO Title:** 50-60 chars. **Main Keyword** must be at the very start.
- **SEO Description:** 150-160 chars.
- **Sentence Case:** Use sentence case for H2-H6.
- **Prohibited Characters:** **No em-dashes (`—`).** Use hyphens (`-`).

#### 5b. The Sapo (Intro)
- **Constraint:** Must be **under 100 characters**.
- **Keyword:** Must contain the **Main Keyword**.

#### 5c. Main Content Rules
- **Proportion:** Main Content sections must be > 90% of the total word count.
- **Answer-First:** Every H2 section must open with a 40-60 word paragraph.

#### 5d. Image Asset Boxes (Visible & Structured)
Every H2 and H3 placement **must** use a visible blockquote box (formatted with code blocks for prompts) to prevent a "wall of text":

--------------------------------------------------
**🎨 IMAGE ASSET: {slug-friendly-name}.jpg**
- **Alt Text:** {Descriptive sentence including keywords}
- **Dimensions:** 800px Width | Flexible Height
- **Gemini Prompt:**
```
{Highly detailed prompt optimized for Gemini: specify subject, action, environment, lighting, style, and composition.}
```
--------------------------------------------------

### Phase 6: Quality Check (Quality Gates)

| Criterion | Limit/Threshold | Action |
|-----------|-----------------|--------|
| **Keyword Logic** | **Main vs Sub** | First keyword must be the primary target |
| **Language** | **English Only** | Remove all Vietnamese terms |
| **Image Density** | **Every H2 & H3** | Ensure no heading is missing an Asset Box |
| **Main Content** | **> 90% of post** | Focus on the core value |
| **Evergreen** | **No Years** | Remove specific year mentions |
| **Conclusion** | **Correct Heading** | Use "Wrap Up", "Final Thoughts", etc. |

### Phase 7: Delivery & Export (Direct Google Doc Upload)

Every completed post must be converted and uploaded **directly as a native Google Doc**.

1. **Naming Convention:** `{slug}-{YYYY-MM-DD-HHmm}`
2. **Parent Folder ID:** `1jFStWmWXJQtUAS5YTpo3SNebpDZVY98A`
3. **Execution Command:**
```bash
TIMESTAMP=$(date +"%Y-%m-%d-%H%M")
pandoc {filename}.md -o "{slug}-$TIMESTAMP.docx"
gdrive files upload --parent 1jFStWmWXJQtUAS5YTpo3SNebpDZVY98A --mime application/vnd.google-apps.document "{slug}-$TIMESTAMP.docx"
```

Present the completed article and the final native Google Doc link to the user.
