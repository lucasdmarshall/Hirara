# Local browser companion

A borderless, responsive layout with custom authentication picker, permission
checkbox/disclosure, keyboard interaction and reduced-motion support. HTML,
CSS, JavaScript and assets are embedded in the Rust binary; there is no frontend
build dependency or runtime CDN request.

`frame.html` contains the `{{NONCE}}`, `{{STYLE}}`, `{{SCRIPT}}` and `{{CONTENT}}`
markers used by the Rust renderer. Preserve these exact markers; disable embedded
language formatting when formatting the HTML template. CSP remains nonce-based,
with images/fonts restricted to this origin. The asset endpoint serves only its
explicit embedded-file allowlist.

## Assets

- `assets/hirara-logo.png` is an unchanged copy of the repository README's
  `assets/hirara-logo.png`. Update the bundled copy when the canonical logo changes.
- Poppins Regular, Medium and SemiBold come from the
  [Google Fonts Poppins sources](https://github.com/google/fonts/tree/main/ofl/poppins).
  Their SIL Open Font License and copyright notice are included in
  `assets/poppins-license.txt`, also available at `/local/assets/poppins-license.txt`.

Browser verification covers desktop/mobile layout, keyboard selection and Escape,
authentication-dependent fields, explicit and named permissions, successful
approval, same-origin font/logo loading and reduced motion.
