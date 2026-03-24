# Dashboard Visual Redesign - Specification

**Date:** 2026-03-23
**Project:** MedContract - Clinical Management System
**Scope:** Complete visual overhaul of dashboard UI
**Status:** Design Approved

---

## 1. OBJECTIVE

Redesign the MedContract dashboard for a modern, professional healthcare aesthetic that prioritizes trust, accessibility, and clarity. The new design maintains functional structure while dramatically improving visual cohesion, readability, and user confidence.

---

## 2. DESIGN PRINCIPLES

- **Healthcare-First**: Convey trust, reliability, and professionalism
- **Accessibility**: Clear hierarchy, high contrast, readable text sizes
- **Clean & Calm**: Ample whitespace, minimal visual noise, zen aesthetic
- **Modern Professional**: Contemporary design language without trendy elements
- **Brand-Aligned**: Utilize clinic's primary color (#2b6c7e) throughout

---

## 3. COLOR PALETTE

### 3.1 Primary Colors

| Role | Hex | Usage |
|------|-----|-------|
| Clinic Primary | `#2b6c7e` | Buttons, accents, headers, brand identity |
| Clinic Hover | `#3d8fa3` | Hover states, secondary emphasis |
| Clinic Active | `#1f4d5f` | Pressed/active states, depth |
| Success | `#059669` | Positive metrics, confirmations |
| Warning | `#d97706` | Attention-needed, cautionary states |
| Danger | `#dc2626` | Critical alerts, urgent action |

### 3.2 Neutral Colors - Light Mode

| Element | Hex | Usage |
|---------|-----|-------|
| Background | `#ffffff` | Page background |
| Surface | `#f8fafc` | Card/panel backgrounds |
| Text Primary | `#0f172a` | Main text content |
| Text Secondary | `#64748b` | Helper text, labels |
| Border | `#e2e8f0` | Lines, dividers, card borders |

### 3.3 Neutral Colors - Dark Mode

| Element | Hex | Usage |
|---------|-----|-------|
| Background | `#0f172a` | Page background |
| Surface | `#1e293b` | Card/panel backgrounds |
| Text Primary | `#f1f5f9` | Main text content |
| Text Secondary | `#cbd5e1` | Helper text, labels |
| Border | `#334155` | Lines, dividers, card borders |

---

## 4. TYPOGRAPHY

### 4.1 Font Stack

```
'Segoe UI', Inter, -apple-system, system-ui, sans-serif
```

Monospace for numeric values:
```
'SF Mono', 'Monaco', 'Courier New', monospace
```

### 4.2 Type Scale

| Level | Size | Weight | Line Height | Usage |
|-------|------|--------|-------------|-------|
| H1 | 28px | 700 | 1.2 | Dashboard title |
| H2 | 20px | 600 | 1.3 | Section headers |
| H3 | 16px | 600 | 1.4 | Card titles |
| Body Large | 16px | 500 | 1.5 | Primary data, emphasis |
| Body | 14px | 400 | 1.5 | Standard text |
| Small | 12px | 400 | 1.4 | Labels, helper text |
| Mono | 14px | 400 | 1.4 | Numeric values |

---

## 5. COMPONENTS

### 5.1 Metric Cards

**Structure:**
```
┌────────────────────────────┐
│ [Icon] Title               │
│                            │
│ 12,450    ← Mono, Large    │
│ ↑ 12% vs last period ← Green
└────────────────────────────┘
```

**Specifications:**
- Border: 1px solid `#e2e8f0` (light) / `#334155` (dark)
- Background: `#ffffff` (light) / `#1e293b` (dark)
- Border radius: 8px
- Padding: 16px
- Shadow: `0 1px 3px rgba(0,0,0,0.1)` (light) / `0 1px 3px rgba(0,0,0,0.3)` (dark)
- Hover state:
  - Background: Subtle shift (1% darker)
  - Shadow: Increase to `0 4px 12px rgba(0,0,0,0.15)`
  - Cursor: pointer
- Icon size: 24px
- Value color: `#2b6c7e` (primary)
- Trend color: `#059669` (green) for positive, `#d97706` for warning

**Responsive:**
- Desktop: 3 columns (gap 12px)
- Tablet: 2 columns
- Mobile: 1 column

### 5.2 Buttons (Action Cards)

**Primary Button:**
- Background: `#2b6c7e`
- Text: `#ffffff`
- Padding: 12px 16px
- Border radius: 6px
- Font: Body (14px, 500)
- Hover: Background `#3d8fa3`, shadow increase
- Active: Background `#1f4d5f`
- Transition: 200ms ease-out
- Cursor: pointer

**Secondary Button:**
- Background: transparent
- Border: 1px solid `#2b6c7e`
- Text: `#2b6c7e`
- Padding: 12px 16px
- Border radius: 6px
- Hover: Background `#f8fafc` (light) / `#1e293b` (dark)

### 5.3 Section Headers

**Structure:**
```
📊 Status dos Contratos
────────────────────────
```

**Specifications:**
- Icon + Text horizontal layout
- Font: H2 (20px, 600)
- Color: `#0f172a` (light) / `#f1f5f9` (dark)
- Border-bottom: 1px solid `#e2e8f0` (light) / `#334155` (dark)
- Padding-bottom: 12px
- Margin-bottom: 16px
- No background

### 5.4 Alert/Error Banner

- Background: Status color with 10% opacity
- Border: 1px solid status color with 30% opacity
- Padding: 12px 14px
- Border radius: 6px
- Text: Status color (darker)
- Icon: Status color

Example (danger):
- Background: `rgba(220, 38, 38, 0.1)`
- Border: `rgba(220, 38, 38, 0.3)`

### 5.5 Loading Bar

- Height: 3px
- Background: `#2b6c7e` (clinic primary)
- Animation: Smooth infinite pulse
- Position: Top of dashboard, always visible when loading
- Z-index: 1000

### 5.6 Input Fields

- Border: 1px solid `#e2e8f0` (light) / `#334155` (dark)
- Background: `#f8fafc` (light) / `#1e293b` (dark)
- Padding: 10px 12px
- Border radius: 6px
- Font: Body (14px)
- Focus: Border color `#2b6c7e`, shadow `0 0 0 3px rgba(43, 108, 126, 0.1)`
- Placeholder: Text secondary color

---

## 6. LAYOUT

### 6.1 Overall Structure

**Single Column Vertical Layout:**

```
┌─────────────────────────────────────────┐
│ TOPBAR (Sticky)                         │
│ Logo | Title | [Period ▼] [Updated]    │
├─────────────────────────────────────────┤
│ ALERTS (if any)                         │
├─────────────────────────────────────────┤
│ QUICK SEARCH                            │
│ [🔍 Search...]                          │
├─────────────────────────────────────────┤
│ 📊 Status dos Contratos                │
├─────────────────────────────────────────┤
│ [Metric 1] [Metric 2] [Metric 3]       │
│ (responsive grid)                       │
├─────────────────────────────────────────┤
│ 📈 Indicadores do Período              │
├─────────────────────────────────────────┤
│ [Metric 1] [Metric 2] [Metric 3]       │
├─────────────────────────────────────────┤
│ ⚡ Ações Rápidas                        │
├─────────────────────────────────────────┤
│ [Button 1] [Button 2]                  │
│ [Button 3] [Button 4]                  │
│ (2 per row, responsive)                │
└─────────────────────────────────────────┘
```

### 6.2 Spacing Standards

| Element | Value | Usage |
|---------|-------|-------|
| Padding (Sections) | 14px left/right | Main content padding |
| Padding (Cards) | 16px | Inside cards |
| Gap (Card Grid) | 12px | Between metric cards |
| Margin (Sections) | 24px | Between major sections |
| Margin (Row) | 12px | Between button rows |

### 6.3 Topbar

- Height: 56px (fixed/sticky)
- Background: `#ffffff` (light) / `#1e293b` (dark)
- Border-bottom: 1px solid `#e2e8f0` (light) / `#334155` (dark)
- Padding: 8px 14px
- Vertical align: center
- Shadow: Very subtle `0 1px 2px rgba(0,0,0,0.05)`
- Content: Logo | Title & Subtitle | [Right: Updated label, Period combo]

### 6.4 Scroll Container

- Main content in scrollable area
- Topbar sticky (doesn't scroll)
- Loading bar appears above topbar
- Padding-bottom of content: 20px (bottom breathing room)

---

## 7. LIGHT MODE vs DARK MODE

### 7.1 Toggle Mechanism

- User preference stored in local storage
- System preference detection (OS dark mode)
- Toggle in appropriate location (TBD - likely settings/topbar)

### 7.2 Color Mapping

All components follow neutral color assignments:
- Light mode: Light backgrounds, dark text
- Dark mode: Dark backgrounds, light text
- Primary/Status colors remain consistent in both modes

### 7.3 Special Considerations

- **Images/Icons**: May need theme-aware variants (if any exist)
- **Shadows**: Slightly darker in dark mode for depth perception
- **Borders**: Slightly lighter in dark mode for contrast

---

## 8. ANIMATIONS & MICRO-INTERACTIONS

### 8.1 Hover States

- **Cards**: Shadow grows, background subtle shift
- **Buttons**: Slight scale (1.02x) or shadow increase
- **Links**: Underline appears or color shifts
- Duration: 200ms
- Easing: ease-out

### 8.2 Loading States

- Loading bar slides/animates
- Metric values fade-in when data arrives
- Duration: 300ms

### 8.3 Focus States

- Input focus: 3px outline in clinic primary color
- Keyboard navigation: Visible focus indicator
- Duration: immediate

### 8.4 Transitions

- Global transition time: 200ms
- Easing curve: ease-out
- Properties: color, background, shadow, transform (for micro-scales)

---

## 9. RESPONSIVE BREAKPOINTS

| Breakpoint | Width | Layout |
|------------|-------|--------|
| Mobile | < 640px | 1 col metric cards, stacked buttons |
| Tablet | 640px - 1024px | 2 col metric cards, 2 col buttons |
| Desktop | > 1024px | 3 col metric cards, 2 col buttons (side-by-side) |

---

## 10. IMPLEMENTATION NOTES

### 10.1 QSS Stylesheet Updates

- Create new QSS file with complete color/style definitions
- Use Qt properties (`#metavar`, `data-severity`, etc.) for state variations
- Define all component types: cards, buttons, labels, inputs
- Include both light and dark mode variants

### 10.2 Files to Modify

- `views/dashboard_view.py` - Update component styling, add dark mode support
- `views/ui_tokens.py` - Add new color palette constants
- `styles/dashboard.qss` (new or updated) - Complete stylesheet

### 10.3 Component Structure (no changes needed)

Current components remain structurally the same:
- MetricCard, LiveMetricCard, CardButton
- HeaderStrip, AlertsPanel
- Only visual styling changes

### 10.4 Dark Mode Implementation

- Add theme manager/toggle mechanism
- Use Qt's QPalette or custom theme class
- Update stylesheet dynamically based on selection
- Persist user preference

---

## 11. ACCEPTANCE CRITERIA

- [ ] All components match color specifications
- [ ] Typography hierarchy is clear and readable
- [ ] Light mode renders correctly with specified colors
- [ ] Dark mode renders correctly with specified colors
- [ ] Hover/focus states work on all interactive elements
- [ ] Loading bar displays with clinic primary color
- [ ] Alert banners show with correct status colors
- [ ] Spacing matches specifications (±2px acceptable)
- [ ] Responsive layout works on mobile/tablet/desktop
- [ ] No accessibility regressions (contrast ratios maintained)
- [ ] User can toggle between light/dark mode
- [ ] Theme preference persists across sessions

---

## 12. APPENDIX: Color Reference

```python
# Python constants for easy reference
CLINIC_PRIMARY = "#2b6c7e"
CLINIC_HOVER = "#3d8fa3"
CLINIC_ACTIVE = "#1f4d5f"
SUCCESS = "#059669"
WARNING = "#d97706"
DANGER = "#dc2626"

# Light mode
LIGHT_BG = "#ffffff"
LIGHT_SURFACE = "#f8fafc"
LIGHT_TEXT_PRIMARY = "#0f172a"
LIGHT_TEXT_SECONDARY = "#64748b"
LIGHT_BORDER = "#e2e8f0"

# Dark mode
DARK_BG = "#0f172a"
DARK_SURFACE = "#1e293b"
DARK_TEXT_PRIMARY = "#f1f5f9"
DARK_TEXT_SECONDARY = "#cbd5e1"
DARK_BORDER = "#334155"
```

---

**Design Document Complete**
**Ready for implementation planning**
