"""
Genesis Colonies – HTML mail layout (dark sci-fi, CTA button + plaintext fallback).
"""

from __future__ import annotations

from html import escape


def build_genesis_mail(
    *,
    subject: str,
    headline: str,
    lead: str,
    cta_label: str,
    cta_url: str,
    footer_note: str = "",
) -> tuple[str, str]:
    """Return (plain_text, html) for transactional mail."""
    safe_url = str(cta_url or "").strip()
    plain = (
        f"{headline}\n\n"
        f"{lead}\n\n"
        f"{cta_label}: {safe_url}\n\n"
        f"{footer_note}\n"
    ).strip()

    h = escape(headline)
    p = escape(lead)
    btn = escape(cta_label)
    url = escape(safe_url)
    foot = escape(footer_note)

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#040810;color:#c8e8f4;font-family:Inter,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#040810;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#060e1c;border:1px solid rgba(70,229,255,0.35);border-radius:4px;overflow:hidden;">
          <tr>
            <td style="padding:14px 18px;background:linear-gradient(180deg,rgba(70,229,255,0.12),rgba(4,10,22,0.2));border-bottom:1px solid rgba(70,229,255,0.2);">
              <div style="font-family:Orbitron,Arial,sans-serif;font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:#46e5ff;">Genesis Colonies</div>
              <div style="font-family:Orbitron,Arial,sans-serif;font-size:18px;font-weight:700;color:#5ee8d0;margin-top:6px;">{h}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 18px 8px;font-size:14px;line-height:1.55;color:#c8e8f4;">{p}</td>
          </tr>
          <tr>
            <td style="padding:8px 18px 18px;" align="center">
              <a href="{url}" style="display:inline-block;padding:12px 22px;background:#0a1828;border:1px solid rgba(70,229,255,0.65);border-radius:3px;color:#46e5ff;font-weight:700;font-size:13px;letter-spacing:0.08em;text-decoration:none;text-transform:uppercase;">{btn}</a>
            </td>
          </tr>
          <tr>
            <td style="padding:0 18px 16px;font-size:12px;line-height:1.45;color:rgba(200,232,244,0.55);word-break:break-all;">{url}</td>
          </tr>
          <tr>
            <td style="padding:12px 18px;border-top:1px solid rgba(70,229,255,0.14);font-size:11px;line-height:1.45;color:rgba(200,232,244,0.45);">{foot}</td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return plain, html
