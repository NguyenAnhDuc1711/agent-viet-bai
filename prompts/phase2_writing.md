# Phase 2: Content Writing

Write a complete, publication-ready blog article in markdown format.

## Input

- **Main Keyword:** {keyword}
- **Research & Strategy Output:**
```json
{research_output}
```
- **Quality Gate Feedback (for revision):** {feedback}

## Writing Rules

### Voice & Tone
- Professional, objective, yet engaging narrative voice.
- All content must be in English.
- Focus on storytelling and expert observation. Minimize raw statistics.

### Structure (AIDA Framework)

#### The Sapo (Introduction)
- Must be **under 100 characters**.
- Must contain the **Main Keyword**.

#### Main Content (Interest + Desire)
- Main Content sections must exceed **90%** of the total article length.
- **Answer-First:** Every H2 section must open with a 40-60 word paragraph that directly answers or addresses the section topic before elaborating.
- Minimum total word count: **2,000 words**.

#### Conclusion
- Use heading like "Wrap Up", "Final Thoughts", or "Key Takeaways" - never just "Conclusion".

### Heading Rules
- Use **sentence case** for H2-H6 headings.
- **Main Keyword** must appear in the Title (at the very start) and in 2-3 H2 headings.
- **Sub-Keywords** distributed naturally throughout H2s and H3s.
- If the title mentions a specific number, provide exactly that many items.

### Prohibited Elements
- **No em-dashes** (`---`). Use hyphens (`-`) instead.
- **No specific years** (e.g., 2025, 2026). Use "current trends" or "latest research."

### Image Asset Boxes
Every H2 and H3 placement MUST include a visible blockquote image asset box immediately after the heading:

> **IMAGE ASSET: {slug-friendly-name}.jpg**
> - **Alt Text:** Descriptive sentence including keywords
> - **Dimensions:** 800px Width | Flexible Height
> - **Gemini Prompt:**
> ```
> Detailed prompt for image generation specifying subject, action, environment, lighting, style, and composition.
> ```

### Visual Density
- No section of text should exceed 400-500 words without a visual break.
- Every H2 and every H3 subsection must include an Image Asset Box.

## Output

Return ONLY the complete markdown article. Do NOT wrap it in JSON or code blocks.
The article should start with the H1 title heading and flow naturally through all sections.
