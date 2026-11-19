# Confluence folder: model deployment investigation

One file = one Confluence page. Files are numbered to match the page tree.

```
00 Model deployment: move to NVIDIA operator approach (Investigation)   ← parent
 ├─ 01 Current deployment approach
 ├─ 02 NVIDIA-recommended approach (high level)
 ├─ 03 Gap analysis
 │    └─ 03a Ticket assessment
 ├─ 04 Risks and constraints
 ├─ 05 Recommendation, phasing and effort
 ├─ 06 Decision record: NeMo microservices CRDs
 └─ Appendices (a parent page "Appendices" with children)
      ├─ A Evidence
      ├─ B Reference: NeMo Helix
      ├─ C Reference: Speech models under the NIM Operator
      └─ D Glossary
```

## Source of truth

- `../project-nemo-operator-investigation.md` is the master. Pages 00–05 were split from it on 2026-11-20.
- When the return sheet comes back, update the **master first**, then re-split (or edit the matching page). Don't let them drift.
- `../return-template.md` → answers go into the master §2/§3, the TBC rows, and Appendix A.

## Placeholders to replace before publishing

| Marker | Do this in Confluence |
|---|---|
| `[MACRO: Page Properties]` + the quoted table | Insert a Page Properties macro; put the table inside |
| `[MACRO: Warning panel]` | Insert a Warning panel with that text |
| `[STATUS: …]` | Insert a Status lozenge (RE-SCOPE = yellow, DEFER = grey, NEW = blue, KEEP = green) |
| `[MACRO: Jira issues]` | Insert the Jira macro with a JQL for those tickets |
| `[MACRO: draw.io]` | Draw the diagram described |
| `[MACRO: Expand]` | Insert an Expand macro around long outputs |
| `[MACRO: Children Display]` | Insert Children Display (or leave the manual list) |
| `[MACRO: Decision]` | Use a Decision macro or a Decision page template |
| `<you>`, `<date>`, `<…>` | Fill in |
| `_TBC_`, `_ask_`, `(confirm …)` | Fill from the return sheet, or move to Open questions |

## Publishing checklist

- [ ] Return sheet answers merged into the master, TBCs resolved or moved to Open questions
- [ ] Re-read pages 00 and 03a in your own words; reword anything that doesn't sound like you
- [ ] No hostnames, IPs, tokens or secrets on any page
- [ ] Every NVIDIA claim has a link and a "checked" date
- [ ] Pre-review with one person (ideally whoever built the current deployment)
- [ ] Status DRAFT → IN REVIEW → final; set "Decision needed by"
- [ ] Share: one message with the bottom line, the decisions needed (with date), and the link

## Pasting tips

- Confluence Cloud: paste Markdown into the editor (or use the `/markdown` insert) and most tables, headings and code blocks convert. Check tables after pasting.
- Data Center/Server: use "Insert → Markup → Markdown", or paste the rendered output from a Markdown previewer.
