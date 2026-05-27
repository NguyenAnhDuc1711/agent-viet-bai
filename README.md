# agent-viet-bai

AI-powered blog writing agent that generates SEO-optimized, high-authority articles designed for both Google rankings and AI citation visibility.

## Features

- **AI-Powered Article Generation** - Complete blog posts from topic, brief, or outline (2,000+ words)
- **Dual Optimization** - Optimized for Google search rankings and AI citation systems
- **SERP & Intent Research** - Competitor analysis and information gap identification
- **AIDA Framework** - Structured outlines (Attention, Interest, Desire, Action)
- **E-E-A-T Signals** - Experience, Expertise, Authority, Trust markers
- **Visual Asset Planning** - Gemini-optimized image prompts for every H2/H3
- **Quality Scoring** - 5-category scoring: Content (30), SEO (25), E-E-A-T (15), Technical (15), AI Citation (15)
- **Google Doc Export** - Automated pandoc conversion and gdrive upload

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Skill definitions | Markdown (YAML frontmatter) |
| Automation | Bash scripts |
| Project management | CCPM (Claude Code Project Manager) |
| Content export | Pandoc (MD → DOCX) |
| File upload | gdrive CLI |

## Getting Started

### Prerequisites

- [pandoc](https://pandoc.org/) - Document conversion
- [gdrive](https://github.com/prasmussen/gdrive) - Google Drive CLI
- [Claude Code](https://claude.com/claude-code) or Gemini - AI agent runtime

### Usage

The agent is invoked through AI coding assistants. The main skill file (`SKILL.md`) defines the blog writing workflow with 7 phases:

1. **Topic & Keyword Understanding** - Clarify audience, keywords, word count
2. **Deep SERP & Intent Research** - Analyze competitors, map keywords
3. **AIDA Outline Generation** - Structure with visual density planning
4. **Content Writing** - High-authority narrative with answer-first formatting
5. **Quality Check** - Verify against quality gates
6. **Delivery & Export** - Convert to DOCX and upload to Google Drive

## Project Structure

```
agent-viet-bai/
├── SKILL.md              # Blog writing skill definition
├── AGENTS.md             # Claude Code agent instructions
├── GEMINI.md             # Gemini agent instructions
├── .ccpm/                # Project management runtime data
└── skill/ccpm/           # CCPM project management skill
    ├── references/       # Command reference docs
    ├── scripts/          # Automation scripts
    ├── hooks/            # Lifecycle hooks
    └── agents/           # Agent definitions
```

## Project Management

This project uses CCPM (Claude Code Project Manager) for spec-driven development workflows. Run `/ccpm <command>` to manage PRDs, epics, and tasks.
