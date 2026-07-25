# Operator Web App Visual Redesign Design

## Purpose

This design defines the visual redesign of the `mitemshub-indices` private operator app after version 1 proved the product workflow but not the design quality.

The redesign goal is not to change the product's core function. It is to transform the interface from a generic, dark, card-heavy dashboard into a premium light-theme operator workspace with stronger hierarchy, typography, trust cues, and motion discipline.

## Why This Exists

The current app works, but its presentation is below the required bar:

- too dark and generic
- too card-like
- weak typography
- weak hierarchy between the market call and support panels
- insufficient visual distinction between operator-critical and secondary information
- not aligned closely enough with the quality bar implied by `mitems-studio-os`

The redesign must fix quality, not just decorate the existing layout.

## External Design Standard

The redesign must use:

- `external/mitems-studio-os`

as the governing design and implementation reference.

The most relevant source chapters for this redesign are:

- `06-COLOR_SYSTEM.md`
- `07-TYPOGRAPHY_SYSTEM.md`
- `09-LAYOUT_SYSTEM.md`
- `10-GRID_SYSTEM.md`
- `15-DESIGN_TOKENS.md`
- `16-DASHBOARD_DESIGN.md`
- `23-MOTION_SYSTEM.md`
- `33-TAILWIND_GUIDE.md`
- `34-FRAMER_MOTION_GUIDE.md`

The strongest style reference inside that repo for this task is:

- `references/stripe.md`

That reference matters because it shows the kind of light-theme fintech trust architecture this redesign should borrow from:

- disciplined typography
- restrained accent color
- editorial spacing
- premium-but-serious information design

## Scope

This redesign covers:

1. The visual system of the existing operator app.
2. The page composition and hierarchy of the main workspace.
3. The design treatment of:
   - command bar
   - main call surface
   - trade instruction surface
   - prop compliance surface
   - review/system surface
   - recent history surface
4. The light-theme token system and typography direction.
5. Motion and interaction polish for symbol switching and mode switching.
6. Cleanup of any obvious hydration-risk patterns discovered during redesign verification.

## Non-Goals

- Replacing the existing product workflow.
- Replacing the backend bridge contract.
- Replacing the prop-firm logic model.
- Turning the app into a public marketing site.
- Adding new product modules unrelated to the current operator workflow.
- Rebuilding the app around charts or dashboard widgets just for appearance.

## Chosen Direction

The selected direction is:

- `Hybrid`
- `light theme only`

This means:

- institutional operator structure
- editorial fintech polish
- premium product restraint

It explicitly rejects:

- dark-mode trading terminal aesthetics
- crypto-neon styling
- generic SaaS dashboards
- decorative AI-slop gradients

## Visual Thesis

The interface should feel like a premium financial briefing desk:

- bright but not sterile
- precise but not cold
- elegant but not soft
- serious enough for operator use
- polished enough to build trust immediately

The mood should combine:

- the scanning clarity of institutional trading software
- the trust architecture of top-tier fintech products
- the compositional discipline of editorial product design

## Content Hierarchy

The redesigned page should operate as three primary planes, not a pile of equal cards.

### Plane 1: Command Rail

This is the operator control layer.

It must contain:

- workspace identity
- symbol triggers for `R_75` and `R_100`
- account mode toggle for `Own Account` and `Prop Firm`
- status/freshness signal
- operator mode signal

It should feel like command hardware translated into a browser UI:

- compact
- crisp
- intentional

It must not feel like a toolbar made of random pill buttons.

### Plane 2: Main Decision Stage

This is the dominant stage of the page and the highest-value surface in the app.

It must give overwhelming hierarchy to:

- current call
- symbol
- confidence
- direction bias
- regime
- rationale
- wait-for guidance

This surface should read like the headline of a financial briefing, not a KPI tile.

### Plane 3: Execution And Oversight Band

This is the support intelligence layer beneath or beside the main decision stage.

It contains:

- trade instruction
- prop compliance
- review/system
- recent history

These surfaces remain important, but they must visually subordinate themselves to the main decision stage.

## Theme System

The redesign is light-theme only in this phase.

### Base Palette

The app should use:

- warm ivory, bone, or soft paper tones for the base
- graphite and ink for text
- restrained accent color, likely deep blue, deep green, or muted amber
- disciplined separators, hairlines, and low-contrast structure

The palette must communicate:

- trust
- clarity
- seriousness

It must avoid:

- pure white everywhere
- cheap gradients
- multicolor dashboards
- aggressive saturation

### Token Rule

The redesign should convert the app from ad hoc utility coloring to a real tokenized visual system aligned with `15-DESIGN_TOKENS.md` and `33-TAILWIND_GUIDE.md`.

Color, spacing, radius, shadow, and motion decisions should be promoted into reusable tokens rather than scattered arbitrary values.

## Typography

Typography is one of the main redesign levers.

The app should use no more than two typefaces:

- one characterful, premium display or editorial face
- one disciplined functional sans for utility and dense reading

Typography should do most of the hierarchy work:

- oversized, high-authority current call heading
- restrained utility labels
- tighter text for support panels
- clearer distinction between decision text and system text

The app must stop relying on default sans text plus cards to create hierarchy.

## Layout Rules

The redesign should follow the spirit of:

- `09-LAYOUT_SYSTEM.md`
- `10-GRID_SYSTEM.md`
- `16-DASHBOARD_DESIGN.md`

### Specific Layout Intent

- reduce stacked-card symmetry
- increase spatial contrast between dominant and secondary zones
- use alignment and whitespace more aggressively
- create one obvious focal point on first load
- prevent the support panels from competing with the primary call stage

The page should feel composed, not assembled.

## Surface Treatment

The redesign should reduce visible card-ness.

That does not mean zero containers. It means:

- fewer repeated box metaphors
- more section framing
- more use of spacing and lines instead of repeated borders and rounded panels
- stronger visual difference between primary and secondary surfaces

The current design problem is not "too few panels." It is "everything looks like the same panel."

## Motion

Motion must be guided by:

- `23-MOTION_SYSTEM.md`
- `34-FRAMER_MOTION_GUIDE.md`

### Required Motion Ideas

The redesigned app should ship at least three intentional motion behaviors:

1. symbol-triggered refresh motion
   - the main decision stage should animate in like a fresh briefing

2. account-mode transition
   - switching to `Prop Firm` should reveal the compliance layer with controlled seriousness

3. page-load choreography
   - the page should settle in with a premium, restrained sequence rather than pop in flatly

Motion must:

- support hierarchy
- remain fast
- remain subtle
- respect reduced motion

It must not:

- become decorative noise
- slow down command use

## Component-Level Redesign Goals

### Command Bar

Redesign to feel like a professional command surface.

Goals:

- cleaner symbol actions
- stronger active state
- refined toggle treatment
- better density
- better brand/workspace framing

### Primary Call Panel

Redesign as the hero surface of the app.

Goals:

- make the current call unforgettable
- improve scanning order
- separate rationale from utility metadata
- make wait-for guidance feel operational, not ornamental

### Trade Instruction Panel

Redesign to feel like execution guidance, not a support card.

Goals:

- clearer numerical hierarchy
- stronger framing for entry/stop/target
- cleaner manual action language

### Prop Compliance Panel

This should feel like policy overlay, not just another informational tile.

Goals:

- more formal visual treatment
- sharper distinction between allowed, adjusted, blocked states
- better emphasis on compliance status and remaining buffers

### Review/System Panel

This should be quieter and more operational.

Goals:

- concise system scanning
- lower visual priority than decision stage
- better utility copy

### History Panel

This should provide context without competing with the live result.

Goals:

- quieter row treatment
- more readable chronology
- less duplication of the primary call surface

## Hydration Warning Handling

The currently observed hydration mismatch appears to involve a `data-theme="light"` attribute added to `<html>` even though `RootLayout` does not render it.

Current interpretation:

- likely preview/browser/extension injection
- not yet evidence of a true product bug

However, redesign verification must still confirm:

- no app-owned server/client branching on theme state
- no unstable SSR values like random/time-driven rendering in the main shell
- no app-authored hydration mismatch in the redesigned implementation

This is a validation requirement, not the primary redesign driver.

## Implementation Direction

The redesign should be implemented directly in the current website repo:

- `external/mitemshub-indices`

It must reuse the working product structure and improve the visual system in place rather than rewriting the entire app from zero.

Expected implementation focus:

- `app/globals.css`
- `app/layout.tsx`
- operator components under `src/components/operator`
- possibly token helpers or structured style constants if needed

## Success Criteria

The redesign is successful when:

- the app is unmistakably light-theme and premium
- the current live call becomes the dominant visual anchor
- the page feels like an operator workspace, not a generic dashboard
- `Prop Firm` mode feels like a real policy overlay
- typography and spacing carry hierarchy more than cards and borders
- the result is visibly aligned with the standards in `mitems-studio-os`
- the app preserves its working product flow while materially improving trust and aesthetics
