# Accessibility statement

We want the web interface to be usable by as many people as possible, including
people who use screen readers, keyboards only, or high zoom.

## Commitment

Our target for the web UI is WCAG 2.1 level AA. New UI work should provide
keyboard-operable controls, visible focus, sufficient colour contrast, text
alternatives for non-text content, and labels for form fields.

## Current status

This is a target, not a certification. **We have not yet done a formal
accessibility audit** of the web UI, so conformance is not claimed.

## Supported environments

The web UI is developed and checked against current versions of Chrome, Firefox,
Safari and Edge on desktop. Screen-reader and mobile support have not been
systematically tested.

## Known limitations

- No formal WCAG audit or screen-reader test pass has been done yet.
- The terminal client (`packages/tui`) and the herdr plugin are text interfaces;
  their behaviour with screen readers depends on the terminal in use and has not
  been tested.
- Interactive visualisations (such as the org chart) may not have a complete
  text alternative.

## Reporting a barrier

If you hit an accessibility barrier, open an issue using the bug report template
and choose the "Web UI" area, or email **bilgi@kuntaykunt.com**. Tell us the page,
the assistive technology or browser you use, and what you were trying to do. We
aim to acknowledge reports within a few working days.
