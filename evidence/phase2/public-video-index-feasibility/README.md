# Public video index feasibility: DNS guard stopped before HTTP

This is a real, bounded feasibility diagnostic, not a search/recommendation acceptance result. The original ceiling was six HTTP requests total (robots included), two per source, zero automatic retries and zero redirects. Actual HTTP requests: **0**.

The existing Fetcher used its system resolver and public-IP validation. Each target returned at least one non-public DNS address and was stopped by `UnsafeURL` before its robots request:

| Target | Observed result | What remains unknown |
| --- | --- | --- |
| `https://www.pygame.org/wiki/tutorials` | DNS answer rejected; no HTTP | robots permission, index availability, tutorial anchors and video identity |
| `https://www.techwithtim.net/` | DNS answer rejected; no HTTP | robots permission, public Pygame directory and video identity |
| `https://docs.arduino.cc/built-in-examples/` | DNS answer rejected; no HTTP | robots permission, examples index and whether any entries bind to videos |

These outcomes do **not** establish that the websites are unavailable or lack relevant videos. No robots policy or access restriction was bypassed, no player/media/private API was requested, and no database, production configuration or frozen backend source was changed.

The first diagnostic omitted `UnsafeURL` from its local reporting catch and stopped with zero HTTP requests. Its saved report was retained, the reporting-only catch was corrected, and `--resume-unattempted` checked only the two remaining hosts. The Pygame target was not repeated. The parent subsequently raised its local diagnostic ceiling to twelve HTTP requests, including DoH, but that message arrived after the two remaining system-DNS checks had also stopped. No alternative DNS retry was performed in this report.

Machine-readable evidence: `report.json`. Script: `../inspect_public_video_indexes.py`. No new adapter path or tutorial coverage claim can be supported from this run. A separate authorized diagnostic using the application's existing trusted public DNS resolver would be needed to evaluate the remaining public indices; all existing URL, address, robots and response restrictions would still apply.
