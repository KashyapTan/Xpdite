# Code Review — Inline SVG Icons

## Review pipeline
- Reviewer A — Correctness & Logic
- Reviewer B — Security & Resilience
- Reviewer C — Performance & Quality
- Judge synthesis pass

## Problems found and fixes
1. **Bolt/session icon semantics were wrong in the shared icon set**
   - Fixed by replacing the old placeholder geometry with a real lightning-bolt path in `src/ui/components/icons/iconPaths.ts` and reusing it from `AppIcons.tsx`.

2. **Slash-command chip remove button needed explicit non-submit semantics**
   - Fixed by adding `type="button"` in `src/ui/components/input/SlashCommandChips.tsx`.

3. **QueryInput duplicated X icon path data and wrote raw label strings into DOM metadata**
   - Fixed by extracting shared SVG paths into `src/ui/components/icons/iconPaths.ts`.
   - Fixed by normalizing tooltip/ARIA label text before assigning `title` and `ariaLabel` in `src/ui/components/input/QueryInput.tsx`.

4. **Tab close buttons were less discoverable for keyboard users**
   - Fixed by making the close icon visible on `:focus-within` / `:focus-visible` in `src/ui/CSS/TabBar.css`.

5. **Dead commented new-tab JSX remained in `TabBar.tsx`**
   - Fixed by removing the obsolete commented block.

6. **Meeting recording processing banner duplicated CSS layout rules inline**
   - Fixed by leaving only the unique inline margin and relying on `meeting-detail-banner-processing-header` CSS for layout.

## False positives / non-blockers
- The earlier attribute-injection concern in `QueryInput.tsx` was mitigated by using normalized DOM label text and DOM property assignment.
- Remaining `bun run lint -- --ignore-pattern .venv` warnings are pre-existing hook/fast-refresh warnings outside the scope of this icon refactor.

## Validation
- `bun run lint -- --ignore-pattern .venv` — passes with pre-existing warnings only
- `bun run build:react`
- `uv run ruff check .`
- `uv run python -m pytest tests/ -v`
