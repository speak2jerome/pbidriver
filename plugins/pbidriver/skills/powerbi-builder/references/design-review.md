# Design review: how a page looks

Two kinds of screenshots serve two jobs:

| Job | Call | You get |
|---|---|---|
| Find and refer to visuals | `pbi_shot annotate=true` | each visual boxed and labelled with its index and type |
| Judge how the page looks | `pbi_shot clean=true` (add `scale=2` for detail) | the page as a viewer sees it: no overlay, no selection outline, hover header, tooltip or open menu |
| Check layout precisely | `pbi_shot overlay=[...]` | chosen measurements drawn on the page |

Every one of them also returns `legend`: each visual's index, type, label, `box` [x, y, width, height] in page
units (the same numbers `pbi_add_visual` takes, read from the report file when it matches the screen) and `id`
(its folder in the PBIR files). `clean=true` and the geometric overlays also return `layout`:

- `issues`: `overlap` (two content visuals overlap; shapes, images and buttons count as decoration),
  `near_alignment` (two edges more than 1 and at most 6 units apart: meant to line up but don't),
  `uneven_gap` (a neighbour gap more than 1 and at most 6 units away from `usual_gap`), `off_page` (sticks out
  of the page). Bigger differences are treated as intentional, so also look at `gaps` and the image.
- `usual_gap`: the most common spacing between neighbouring visuals.
- `gaps`: every neighbour spacing found (neighbours up to 1/8 of the page apart).

`pbi_add_visual shot=true clean=true` gives the clean capture plus the layout check right after an edit.

## Overlay items

| Item | Draws |
|---|---|
| `index`, `type` | the label `annotate=true` draws |
| `title` | the visual's title or label |
| `size` | width x height in page units |
| `pos` | x, y in page units |
| `errors` | red fill on visuals showing an error |
| `perf` | render time per visual from Performance Analyzer (green, amber, red against `threshold`, default 500 ms); takes a few seconds |
| `grid` | a grid every `grid_size` units (default 40), stronger every 5th line |
| `align` | orange lines on edges that almost line up |
| `gaps` | spacing between neighbours (blue; orange when uneven) |
| `overlap` | red fill where visuals overlap |
| `all` | everything except `perf` |

Overlays are drawn on whole-canvas captures only (not with `visual=`, `all_visuals` or `full`).

## A review pass

1. `pbi_shot clean=true scale=2` and look at it as a viewer would: is the most important number top left? Is
   anything cramped, cut off, empty, or showing an error? Are titles clear and consistent?
2. Read `layout.issues` and fix each one: move or resize visuals so edges line up, gaps match `usual_gap`, and
   nothing overlaps. To move or resize, edit `position` (`x`, `y`, `width`, `height`) in
   `<Name>.Report/definition/pages/<pageId>/visuals/<id>/visual.json` (the `id` is in `legend` and `pbi_layout`),
   then `pbi_reload report_only=true`; or `pbi_remove_visual` and `pbi_add_visual` with the corrected numbers.
3. `pbi_shot overlay=[index, size, pos, gaps]` to confirm the numbers, then `clean=true` again for the final look.

## Rules of thumb

- Keep one margin and one gap everywhere (for example 20 units), and line up columns and rows.
- Big numbers (cards) in a row at the top, the main chart below, details last or on another page.
- 6 to 10 visuals per page; more gets slow and busy (see `pbi_guide topic=performance`).
- Titles say what the visual answers ("Revenue by region"), not the field names.
- Labels must not truncate: widen the visual, shorten the title, or use a bar chart for long category names.
- A slicer belongs in a consistent place (top right or a left column) on every page.
