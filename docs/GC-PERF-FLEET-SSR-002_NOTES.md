# GC-PERF-FLEET-SSR-002 — Next Slice Notes

Current `/fleet` SSR still builds both the normal fleet page context and `build_logistics_page_context`, even though the UI only displays one mode at a time. `fleet.html` likewise keeps both the full send markup and embedded Logistics markup in the response.

Next backend slice after GC-PERF-FLEET-TABS-001:

1. Resolve requested mode before heavy page-context construction.
2. Send mode: build only `build_fleet_page_context`; do not tick/load every colony for Logistics.
3. Collect/Distribute mode: build the minimal Fleet shell data plus `build_logistics_page_context`; avoid rendering the full ship-send catalog when it is hidden.
4. Preserve one `/fleet` route, Planet Scope, server authority and existing Logistics owner/API.
5. Add SSR phase regression/perf assertions so hidden modes cannot reintroduce heavy context work.
