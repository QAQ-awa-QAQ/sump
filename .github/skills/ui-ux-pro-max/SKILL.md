---
name: ui-ux-pro-max
description: "UI/UX design intelligence for web and mobile. Searchable local database with 84 styles, 192 color palettes, 74 font pairings, 192 product types, 98 UX guidelines, 104 icon entries, 16 GSAP motion presets, and 25 chart types across 22 stacks (React, Next.js, Vue, Nuxt, Svelte, Astro, SwiftUI, React Native, Flutter, Tailwind, shadcn/ui, Jetpack Compose, Angular, Laravel, JavaFX, WPF, WinUI, Avalonia, Uno Platform, UWP, Three.js, HTML/CSS). Use when designing, building, reviewing, or improving UI: pages, components, color schemes, typography, layout, accessibility, animation, data visualization, landing page, dashboard, mobile app, dark mode, responsive design."
argument-hint: "Build a landing page for my SaaS product"
---

# UI/UX Pro Max - Design Intelligence

## When to Apply

Use this Skill when the task involves **UI structure, visual design decisions, interaction patterns, or user experience quality control**: designing new pages, creating/refactoring UI components, choosing color/typography/spacing/layout systems, reviewing UI for UX/accessibility/consistency, implementing navigation/animation/responsive behavior, or improving perceived quality and usability.

Skip it for pure backend logic, API/database design, non-visual performance work, infrastructure/DevOps, or non-visual scripts — unless the task changes how something **looks, feels, moves, or is interacted with**.

## Rule Categories by Priority

*Follow priority 1→10 to decide which category to focus on first; use `--domain <Domain>` to query full details. The full rule text for every category lives in [references/quick-reference.md](./references/quick-reference.md) — read it on demand rather than loading it every time.*

| Priority | Category | Impact | Domain | Key Checks (Must Have) | Anti-Patterns (Avoid) |
|----------|----------|--------|--------|------------------------|------------------------|
| 1 | Accessibility | CRITICAL | `ux` | Contrast 4.5:1, Alt text, Keyboard nav, Aria-labels | Removing focus rings, Icon-only buttons without labels |
| 2 | Touch & Interaction | CRITICAL | `ux` | Min size 44×44px, 8px+ spacing, Loading feedback | Reliance on hover only, Instant state changes (0ms) |
| 3 | Performance | HIGH | `ux` | WebP/AVIF, Lazy loading, Reserve space (CLS < 0.1) | Layout thrashing, Cumulative Layout Shift |
| 4 | Style Selection | HIGH | `style`, `product` | Match product type, Consistency, SVG icons (no emoji) | Mixing flat & skeuomorphic randomly, Emoji as icons |
| 5 | Layout & Responsive | HIGH | `ux` | Mobile-first breakpoints, Viewport meta, No horizontal scroll | Horizontal scroll, Fixed px container widths, Disable zoom |
| 6 | Typography & Color | MEDIUM | `typography`, `color` | Base 16px, Line-height 1.5, Semantic color tokens | Text < 12px body, Gray-on-gray, Raw hex in components |
| 7 | Animation | MEDIUM | `ux`, `gsap` | Duration 150–300ms, Motion conveys meaning, Spatial continuity | Decorative-only animation, Animating width/height, No reduced-motion |
| 8 | Forms & Feedback | MEDIUM | `ux` | Visible labels, Error near field, Helper text, Progressive disclosure | Placeholder-only label, Errors only at top, Overwhelm upfront |
| 9 | Navigation Patterns | HIGH | `ux` | Predictable back, Bottom nav ≤5, Deep linking | Overloaded nav, Broken back behavior, No deep links |
| 10 | Charts & Data | LOW | `chart` | Legends, Tooltips, Accessible colors | Relying on color alone to convey meaning |

For the full rule list per category (all ~98 UX guidelines with rationale), read [references/quick-reference.md](./references/quick-reference.md). For app-specific polish rules (icons, touch feedback, dark mode contrast, safe areas) and the canonical pre-delivery checklist, read [references/pro-rules.md](./references/pro-rules.md).

---

## Running the Search Tool

The search script lives inside this skill's own directory. Always invoke it relative to the skill root. The skill root is the directory containing this SKILL.md file.

```bash
python ./scripts/search.py "<query>" --domain <domain>
```

If `python` is not found, try `python3`, then `py -3`. Requires Python 3.x, no external dependencies.

---

## Workflow

### Step 0: Detect the Stack

Detect from the project — check `package.json` deps (react/next/vue/svelte/nuxt/@angular), `pubspec.yaml` (Flutter), `*.xcodeproj`/`Package.swift` (SwiftUI), `composer.json` (Laravel), or React Native markers (`app.json` + `react-native` dep). If nothing is detectable, ask the user or default to `html-tailwind`. **Never assume a stack** — a hardcoded default silently misroutes every recommendation.

### Step 1: Analyze User Requirements

Extract from the user request:
- **Product type**: SaaS, e-commerce, portfolio, dashboard, entertainment, tool, productivity, or hybrid
- **Target audience & context**: age group, usage context (commute, leisure, work)
- **Style keywords**: playful, vibrant, minimal, dark mode, content-first, immersive, etc.

### Step 2: Generate Design System (REQUIRED for new pages/projects)

Always start with `--design-system` to get comprehensive recommendations with reasoning:

```bash
python ./scripts/search.py "<product_type> <industry> <keywords>" --design-system [-p "Project Name"]
```

This searches product/style/color/landing/typography domains in parallel, applies reasoning rules from `ui-reasoning.csv`, and returns pattern, style, colors, typography, effects, and anti-patterns to avoid.

**Example:**
```bash
python ./scripts/search.py "beauty spa wellness service" --design-system -p "Serenity Spa"
```

### Step 2b: Persist Design System (Master + Overrides Pattern)

To save the design system for retrieval across sessions, add `--persist` **and always pass `--output-dir` pointed at the project root**:

```bash
python ./scripts/search.py "<query>" --design-system --persist -p "Project Name" --output-dir "<project-root>"
```

This creates:
- `design-system/<project-slug>/MASTER.md` — Global Source of Truth
- `design-system/<project-slug>/pages/` — Folder for page-specific overrides

If `design-system/<project-slug>/MASTER.md` already exists, `--persist` **skips writing** unless you also pass `--force`.

**Retrieval when building a specific page:**
1. Read `design-system/<project-slug>/MASTER.md`
2. Check if `design-system/<project-slug>/pages/<page-name>.md` exists — if so, its rules override Master
3. Otherwise use Master rules exclusively

### Step 2c: Design Dials (optional)

Three optional 1-10 sliders that tune `--design-system` output:

```bash
python ./scripts/search.py "<query>" --design-system --variance <1-10> --motion <1-10> --density <1-10>
```

| Dial | Low (1-3) | Mid (4-7) | High (8-10) |
|------|-----------|-----------|-------------|
| `--variance` | Centered / minimal | Balanced / modern | Bold / asymmetric |
| `--motion` | Subtle micro-interactions | Standard scroll/stagger | Complex choreography |
| `--density` | Spacious (24-96px spacing) | Standard (16-64px) | Dense/dashboard (8-32px) |

### Step 3: Supplement with Detailed Searches (as needed)

```bash
python ./scripts/search.py "<keyword>" --domain <domain> [-n <max_results>]
```

| Need | Domain | Example |
|------|--------|---------|
| Product type patterns | `product` | `--domain product "entertainment social"` |
| More style options | `style` | `--domain style "glassmorphism dark"` |
| Color palettes | `color` | `--domain color "entertainment vibrant"` |
| Font pairings | `typography` | `--domain typography "playful modern"` |
| Individual Google Fonts | `google-fonts` | `--domain google-fonts "sans serif popular variable"` |
| Chart recommendations | `chart` | `--domain chart "real-time dashboard"` |
| UX best practices | `ux` | `--domain ux "animation accessibility"` |
| Landing page structure | `landing` | `--domain landing "hero social-proof"` |
| Icon recommendations | `icons` | `--domain icons "navigation outline"` |
| GSAP animation presets | `gsap` | `--domain gsap "scroll reveal stagger"` |
| React/Next.js performance | `react` | `--domain react "rerender memo list"` |
| App/native interface guidelines | `web` | `--domain web "accessibilityLabel touch safe-areas"` |

Domain is auto-detected from the query if `--domain` is omitted.

### Step 4: Stack Guidelines

```bash
python ./scripts/search.py "<keyword>" --stack <stack>
```

**Available stacks:** `react`, `nextjs`, `vue`, `svelte`, `astro`, `nuxtjs`, `nuxt-ui`, `angular`, `laravel`, `swiftui`, `react-native`, `flutter`, `jetpack-compose`, `html-tailwind`, `shadcn`, `threejs`, `javafx`, `wpf`, `winui`, `avalonia`, `uno`, `uwp`.

---

## If a Search Returns 0 Results

Do not fabricate output. Instead:
1. Retry once with broader or differently-worded keywords.
2. If still empty, fall back to the priority table above and say explicitly that this recommendation came from built-in defaults, not a database match.
3. Never present a 0-result search as if it returned data.

---

## Example Workflow

**User request:** "Make an AI search homepage." (stack detected as Next.js from `package.json`)

```bash
# Step 2: design system
python ./scripts/search.py "AI search tool modern minimal" --design-system -p "AI Search"

# Step 3: supplement
python ./scripts/search.py "search loading animation" --domain ux

# Step 4: stack guidelines
python ./scripts/search.py "suspense streaming bundle" --stack nextjs
```

Then synthesize the design system + detailed searches and implement.

---

## Output Formats

`--design-system` supports `-f ascii` (default, terminal display), `-f markdown` (documentation), and `--json` (machine-readable).

---

## Tips for Better Results

- Use **multi-dimensional keywords** — combine product + industry + tone + density: `"entertainment social vibrant content-dense"`, not just `"app"`
- Try different phrasings: `"playful neon"` → `"vibrant dark"` → `"content-first minimal"`
- Use `--design-system` first, then `--domain` to deep-dive
- Pass the detected stack explicitly for implementation-specific guidance

| Problem | What to Do |
|---------|------------|
| Can't decide on style/color | Re-run `--design-system` with different keywords |
| Dark mode contrast issues | [references/quick-reference.md](./references/quick-reference.md) §6 |
| Animations feel unnatural | [references/quick-reference.md](./references/quick-reference.md) §7 |
| Form UX is poor | [references/quick-reference.md](./references/quick-reference.md) §8 |
| Navigation feels confusing | [references/quick-reference.md](./references/quick-reference.md) §9 |
| Layout breaks on small screens | [references/quick-reference.md](./references/quick-reference.md) §5 |
| Performance / jank | [references/quick-reference.md](./references/quick-reference.md) §3 |

---

## Before Delivering App UI

Read [references/pro-rules.md](./references/pro-rules.md) and run through its canonical Pre-Delivery Checklist. It covers icon/visual-element discipline, interaction feedback, light/dark contrast, safe-area layout, and accessibility — scoped to native/mobile app UI (iOS/Android/React Native/Flutter).
