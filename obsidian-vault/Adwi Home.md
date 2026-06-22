---
type: home
status: active
updated: 2026-06-21
---

# Adwi Home

> Your local AI OS — navigation hub for this workspace.
> Open this note to orient yourself. Everything links from here.

---

## Current Focus

*Edit this section manually to reflect what you're working on today.*

- [ ] 

→ See today's note: [[daily-notes/2026-06-21]]

---

## Projects

| Project | Status | Note |
|---------|--------|------|
| Adwi AI OS | 🟢 Active | [[projects/Adwi]] |
| NLU Reliability | 🟢 98.3% combined | [[knowledge/Eval and Reliability Map]] |
| Obsidian as thinking layer | 🟡 In progress | this file |
| Telegram Bridge | ✅ Wave 4 (41 cmds) | [[knowledge/Telegram Control Plane]] |
| CommandRegistry migration | ✅ Phases 7–23 complete | [[knowledge/Automation Map]] |

---

## System Map

Quick orientation — what runs where.

| Layer | What | Where |
|-------|------|-------|
| CLI / REPL | `adwi_cli.py` · 184 commands | `adwi/adwi_cli.py` |
| Primary model | adwi:latest (qwen3:30b) | Ollama :11434 |
| NLU classifier | llama3.1:8b · 115 intents | Ollama :11434 |
| Web search | SearXNG (private) | Docker :8888 |
| Automation | n8n workflows | Docker :5678 |
| Safe API | Safe Command API | Host :5055 |
| Vault API | Obsidian Bridge | Host :5056 |
| Vector DB | Qdrant | Docker :6333 |
| Memory | memory.db + knowledge.db | `adwi/*.db` (gitignored) |
| Monitoring | Grafana / Prometheus / Loki | Docker :4000/:9090/:3100 |
| Remote control | Telegram Bridge | outbound long-poll |

→ Full diagram: [[knowledge/System Map]] · [[System Map.canvas]]
→ Automation flows: [[knowledge/Automation Map]]
→ Memory layer: [[knowledge/Memory and Knowledge Map]]

---

## Roadmap & Ideas

| Idea | Status | Note |
|------|--------|------|
| Voice input (whisper.cpp) | 🔵 Planned | [[projects/ideas/Voice Input]] |
| Screen monitoring | 🔵 Planned | [[projects/ideas/Screen Monitoring]] |
| Multi-agent execution | 🔵 Planned | [[projects/ideas/Multi-Agent Execution]] |
| Implement-from-video | 🔵 Planned | [[projects/ideas/Implement from Video]] |
| Article/URL implementation flow | 🔵 Planned | [[projects/ideas/Article URL Implementation Flow]] |
| Mistake pattern detection | 🔵 Planned | [[projects/ideas/Mistake Pattern Detection]] |
| Conversation memory | 🔵 Planned | [[projects/ideas/Conversation Memory]] |

→ All Adwi ideas: [[knowledge/Ideas Index]]
→ All projects + life ideas: [[knowledge/Master Ideas Index]]
→ Full roadmap: [adwi/notes/adwi-capability-roadmap.md](../adwi/notes/adwi-capability-roadmap.md)

---

## Ideas & Planning

How this workspace handles ideas, prioritization, and new projects.

→ **Master Index:** [[knowledge/Master Ideas Index]] — all projects, ideas, implemented, parked
→ **Ideas OS:** [[knowledge/Ideas Operating System]] — capture → brainstorm → score → promote → build
→ **Workspace structure:** [[knowledge/Workspace Organization]] — what goes where, lifecycle, naming
→ **Implementation guide:** [[knowledge/Implementation Workflow]] — MVP approach, decision docs, archiving
→ **Life automation brainstorm:** [[projects/life-automation/Life Automation Ideas]]

---

## Daily Notes

<!-- ADWI:HOME-STATUS:START -->
*Not yet refreshed — will be populated by the nightly loop (2 AM).*
<!-- ADWI:HOME-STATUS:END -->

*New daily notes are written automatically by `adwi/nightly.py` at 2 AM. The `/daily-brief` command updates today's brief block.*
*See [[knowledge/Obsidian Maintenance]] for how marker blocks work and recovery steps.*
*Review captured items weekly: [[knowledge/Review Workflow]]*
*Generate today's plan: [[knowledge/Planning Workflow]] · `/obsidian-plan`*
*Use templates when creating notes manually: [[knowledge/Template Guide]]*
*Daily playbook: [[knowledge/Obsidian Operator Guide]]*

---

## Troubleshooting

→ [[knowledge/Troubleshooting Log]]
→ [adwi/notes/adwi-mistakes-and-fixes.md](../adwi/notes/adwi-mistakes-and-fixes.md)
→ [adwi/docs/OPERATOR_HANDBOOK.md](../adwi/docs/OPERATOR_HANDBOOK.md)

**Quick recovery commands:**
```bash
/doctor          # full stack health check
/status          # service status
/self-heal       # run diagnostics + auto-fix
/repair-adwi     # 10-check repair pass
```

---

## Pending Approval

Items that Adwi generated but need human review before applying.

→ [[knowledge/Pending Approval]]

*The nightly loop places AI skill suggestions here. Review and apply manually.*

---

## Obsidian Command Cheat Sheet

```bash
/obsidian-status                    # vault summary + last nightly validation
/obsidian-plan 7                    # generate today's plan from last 7 days
/obsidian-capture idea <text>       # capture to daily note + ideas index
/obsidian-review 7                  # grouped summary of last 7 days
/obsidian-review-save 7             # save review to reviews/
/obsidian-promote-idea Title -- desc  # create idea note + link in index
/obsidian-validate                  # full vault health check
/obsidian-help                      # print this cheat sheet
```

→ Full playbook: [[knowledge/Obsidian Operator Guide]] · [[knowledge/Obsidian Upgrade Handoff]]

---

## Useful Commands

```bash
# Navigation
/daily-brief          # morning brief + priorities
/what-next            # AI-suggested next action
/roadmap              # capability roadmap

# Memory & knowledge
/memory-recall <q>    # search memory + vault
/obsidian-search <q>  # search vault notes
/rag <q>              # RAG over notes index

# System
/doctor               # full health check
/status               # quick status
/nightly-status       # last nightly run
/eval-status          # NLU pass rates

# Research
/research <question>  # deep multi-source research
/tech-radar           # scan AI/dev landscape
/daily-brief          # priorities + inbox + tip
```

---

## How This Vault Works

**What Adwi writes automatically:**
- `daily-notes/YYYY-MM-DD.md` — nightly summary (2 AM) and daily brief (on demand)
- Generated sections are wrapped in `<!-- ADWI:...:START/END -->` markers and replaced, not appended

**What you write manually (or via `/obsidian-capture`):**
- Current Focus, Decisions, Ideas, Bugs / Fixes in daily notes via [[knowledge/Capture Workflow]]
- Any note in `projects/`, `knowledge/`, or `automations/`

**Where things go:**
- New ideas → `projects/ideas/` and [[knowledge/Ideas Index]]
- Decisions → daily note `## Decisions` section
- Bugs / fixes → [[knowledge/Troubleshooting Log]] or daily note
- Research output → `adwi/notes/research/` (from `/research-save`)
- Tech radar → `adwi/notes/tech-radar/` (from `/tech-radar`)

**Backlinks:** Obsidian's backlinks panel shows you every note that links to the current one — use this to navigate from ideas → related knowledge → daily notes.

---

*Workspace: `~/SuneelWorkSpace/` · Entry point: `bin/adwi` · Docs: [adwi/docs/](../adwi/docs/)*
