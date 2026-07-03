from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from real_estate_monitor.models import ChangeType, ListingChange

REPORT_TIMEZONE = timezone(timedelta(hours=2))


@dataclass(frozen=True)
class SiteReportSection:
    site: str
    run_id: int | None
    changes: list[ListingChange]
    error: str | None = None


def _money(value: int | None, currency: str) -> str:
    if value is None:
        return "unknown"
    symbol = "EUR" if currency != "EUR" else "€"
    return f"{symbol}{value:,}"


def _change_line(change: ListingChange) -> str:
    listing = change.listing
    if change.change_type == ChangeType.PRICE_CHANGED and change.previous:
        return (
            f"- Price changed: [{listing.title}]({listing.url}) "
            f"({_money(change.previous.price, listing.currency)} -> {_money(listing.price, listing.currency)})"
        )
    if change.change_type == ChangeType.REMOVED:
        return f"- Removed: {listing.title} ({listing.external_id})"
    return f"- New: [{listing.title}]({listing.url}) ({_money(listing.price, listing.currency)})"


def build_markdown_report(site: str, run_id: int, changes: list[ListingChange]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    counts = Counter(change.change_type for change in changes)
    lines = [
        f"# Real Estate Monitor Report: {site}",
        "",
        f"- Run ID: {run_id}",
        f"- Generated: {now}",
        f"- Total changes: {len(changes)}",
        f"- New listings: {counts[ChangeType.NEW]}",
        f"- Removed listings: {counts[ChangeType.REMOVED]}",
        f"- Price changes: {counts[ChangeType.PRICE_CHANGED]}",
        "",
        "## Changes",
        "",
    ]
    lines.extend(_change_line(change) for change in changes)
    if not changes:
        lines.append("No changes detected.")
    lines.append("")
    return "\n".join(lines)


def build_html_email_report(site: str, run_id: int, changes: list[ListingChange]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    counts = Counter(change.change_type for change in changes)
    rows = "\n".join(_change_row(change) for change in changes)
    if not rows:
        rows = """
        <tr>
          <td colspan="3" style="padding:16px;color:#475569;">No changes detected.</td>
        </tr>
        """

    return f"""<!doctype html>
<html>
  <body style="margin:0;background:#f6f7f9;font-family:Arial,Helvetica,sans-serif;color:#111827;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f7f9;padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="720" cellspacing="0" cellpadding="0" style="width:720px;max-width:96%;background:#ffffff;border:1px solid #e5e7eb;">
            <tr>
              <td style="padding:28px 32px 18px;border-bottom:1px solid #e5e7eb;">
                <div style="font-size:13px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">Real Estate Monitor</div>
                <h1 style="margin:8px 0 8px;font-size:26px;line-height:1.25;color:#0f172a;">{escape(site.title())} Report</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 32px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    {_metric_cell("Total changes", len(changes))}
                    {_metric_cell("New", counts[ChangeType.NEW])}
                    {_metric_cell("Removed", counts[ChangeType.REMOVED])}
                    {_metric_cell("Price", counts[ChangeType.PRICE_CHANGED])}
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 32px;">
                <h2 style="font-size:18px;margin:0 0 12px;color:#0f172a;">Changes</h2>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid #e5e7eb;">
                  <thead>
                    <tr style="background:#f8fafc;">
                      <th align="left" style="padding:10px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#475569;">Type</th>
                      <th align="left" style="padding:10px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#475569;">Listing</th>
                      <th align="left" style="padding:10px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#475569;">Price</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows}
                  </tbody>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def build_combined_markdown_report(sections: list[SiteReportSection]) -> str:
    now = _report_datetime()
    all_changes = [change for section in sections for change in section.changes]
    counts = Counter(change.change_type for change in all_changes)
    lines = [
        "# Market Report",
        "",
        f"- Generated: {now}",
        f"- Total changes: {len(all_changes)}",
        f"- New listings: {counts[ChangeType.NEW]}",
        f"- Removed listings: {counts[ChangeType.REMOVED]}",
        f"- Price changes: {counts[ChangeType.PRICE_CHANGED]}",
        "",
    ]

    for section in sections:
        lines.extend([f"## {_site_display_name(section.site)}", ""])
        if section.error:
            lines.extend([f"Scrape failed: {section.error}", ""])
            continue
        if not section.changes:
            lines.extend(["No changes detected.", ""])
            continue
        lines.extend(_change_line(change) for change in section.changes)
        lines.append("")
    return "\n".join(lines)


def build_combined_html_email_report(sections: list[SiteReportSection]) -> str:
    all_changes = [change for section in sections for change in section.changes]
    counts = Counter(change.change_type for change in all_changes)
    site_blocks = "\n".join(_combined_site_block(section) for section in sections)
    generated = _report_datetime()

    return f"""<!doctype html>
<html>
  <body style="margin:0;background:#f9f9f9;font-family:Futura,'Avenir Next',Arial,sans-serif;color:#181818;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f9f9f9;padding:28px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="820" cellspacing="0" cellpadding="0" style="width:820px;max-width:96%;background:#ffffff;border:1px solid #e7e1d8;">
            <tr>
              <td style="background:#181818;padding:30px 34px;color:#ffffff;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td>
                      <div style="font-size:12px;letter-spacing:.22em;color:#c7af87;text-transform:uppercase;">Drumelia Real Estate</div>
                      <h1 style="margin:9px 0 0;font-size:30px;line-height:1.2;font-weight:500;color:#ffffff;">Market Report</h1>
                    </td>
                    <td align="right" style="font-size:12px;color:#c7af87;">{escape(generated)}</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 34px 18px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    {_combined_metric_cell("Total", len(all_changes))}
                    {_combined_metric_cell("New", counts[ChangeType.NEW])}
                    {_combined_metric_cell("Removed", counts[ChangeType.REMOVED])}
                    {_combined_metric_cell("Price", counts[ChangeType.PRICE_CHANGED])}
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:0 34px 34px;">
                {site_blocks}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _metric_cell(label: str, value: int) -> str:
    return f"""
    <td style="padding:0 8px 0 0;">
      <div style="border:1px solid #e5e7eb;background:#fbfdff;padding:12px;">
        <div style="font-size:12px;color:#64748b;">{escape(label)}</div>
        <div style="font-size:22px;font-weight:bold;color:#0f172a;">{value}</div>
      </div>
    </td>
    """


def _report_datetime() -> str:
    return datetime.now(REPORT_TIMEZONE).strftime("%d %b %Y, %H:%M")


def _combined_metric_cell(label: str, value: int) -> str:
    return f"""
    <td style="padding:0 8px 0 0;">
      <div style="border:1px solid #e7e1d8;background:#f7f7f7;padding:14px 16px;">
        <div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#8a857f;">{escape(label)}</div>
        <div style="font-size:24px;line-height:1.2;font-weight:500;color:#181818;">{value}</div>
      </div>
    </td>
    """


def _combined_site_block(section: SiteReportSection) -> str:
    if section.error:
        rows = f"""
        <tr>
          <td colspan="4" style="padding:13px 12px;border-bottom:1px solid #e7e1d8;color:#84442e;">{escape(section.error)}</td>
        </tr>
        """
    elif section.changes:
        rows = "\n".join(_combined_change_row(change) for change in section.changes)
    else:
        rows = """
        <tr>
          <td colspan="4" style="padding:13px 12px;border-bottom:1px solid #e7e1d8;color:#8a857f;">No changes detected.</td>
        </tr>
        """

    return f"""
    <div style="margin-top:22px;">
      <h2 style="margin:0 0 10px;font-size:18px;line-height:1.25;font-weight:500;color:#181818;">{escape(_site_display_name(section.site))}</h2>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid #e7e1d8;">
        <thead>
          <tr style="background:#181818;">
            <th align="left" style="padding:10px 12px;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#c7af87;">Change</th>
            <th align="left" style="padding:10px 12px;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#c7af87;">Reference</th>
            <th align="left" style="padding:10px 12px;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#c7af87;">Listing</th>
            <th align="left" style="padding:10px 12px;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#c7af87;">Price</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """


def _combined_change_row(change: ListingChange) -> str:
    listing = change.listing
    price = _money(listing.price, listing.currency)
    if change.change_type == ChangeType.PRICE_CHANGED and change.previous:
        price = f"{_money(change.previous.price, listing.currency)} -> {_money(listing.price, listing.currency)}"
    if change.change_type == ChangeType.REMOVED:
        price = _money(listing.price, listing.currency)
    return f"""
    <tr>
      <td style="padding:12px;border-bottom:1px solid #e7e1d8;font-size:13px;color:#84442e;">{escape(_change_label(change.change_type))}</td>
      <td style="padding:12px;border-bottom:1px solid #e7e1d8;font-size:13px;color:#181818;">{escape(listing.external_id)}</td>
      <td style="padding:12px;border-bottom:1px solid #e7e1d8;font-size:13px;"><a href="{escape(listing.url)}" style="color:#181818;text-decoration:underline;text-decoration-color:#c7af87;">{escape(listing.title)}</a></td>
      <td style="padding:12px;border-bottom:1px solid #e7e1d8;font-size:13px;color:#181818;">{escape(price)}</td>
    </tr>
    """


def _change_row(change: ListingChange) -> str:
    listing = change.listing
    price = _money(listing.price, listing.currency)
    if change.change_type == ChangeType.PRICE_CHANGED and change.previous:
        price = f"{_money(change.previous.price, listing.currency)} -> {_money(listing.price, listing.currency)}"
    title = escape(listing.title)
    url = escape(listing.url)
    return f"""
    <tr>
      <td style="padding:10px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#334155;">{escape(change.change_type.value.replace("_", " ").title())}</td>
      <td style="padding:10px;border-bottom:1px solid #e5e7eb;font-size:13px;"><a href="{url}" style="color:#0f766e;text-decoration:none;">{title}</a></td>
      <td style="padding:10px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#334155;">{escape(price)}</td>
    </tr>
    """


def _change_label(change_type: ChangeType) -> str:
    if change_type == ChangeType.PRICE_CHANGED:
        return "Price Change"
    return change_type.value.replace("_", " ").title()


def _site_display_name(site: str) -> str:
    names = {
        "dmproperties": "DM Properties",
        "marbella_ev": "Marbella EV",
    }
    return names.get(site, site.replace("_", " ").title())


def write_report(report_dir: Path, site: str, run_id: int, markdown: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{site}-run-{run_id}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
