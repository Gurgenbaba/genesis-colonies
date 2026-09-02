from pathlib import Path

path = Path("static/main.js")
text = path.read_text(encoding="utf-8")

old_guard = '''    const wbLivePollTick = () => {
      const cards = root.querySelectorAll(".gc-world-boss-card");
'''
new_guard = '''    const wbLivePollTick = () => {
      // GC-PG-WB-POLL-001: never spend a PostgreSQL request on a hidden tab.
      // Countdowns and encounter timers are client-side, so no gameplay state is lost.
      if (document.hidden) return;
      const cards = root.querySelectorAll(".gc-world-boss-card");
'''

old_scheduler = '''    const wbAutoPollId =
      typeof GC.setSafeInterval === "function"
        ? GC.setSafeInterval(wbLivePollTick, 1000)
        : setInterval(wbLivePollTick, 1000);
    if (typeof GC.registerCleanup === "function") {
      GC.registerCleanup(() => {
        if (typeof GC.clearSafeInterval === "function") GC.clearSafeInterval(wbAutoPollId);
        else clearInterval(wbAutoPollId);
      });
    }
'''

new_scheduler = '''    // GC-PG-WB-POLL-001: the old fixed 1s loop kept /api/world-boss almost
    // continuously in flight when the endpoint itself needed multiple seconds.
    // Poll faster only while Auto-Attack is active, back off for normal viewing,
    // and suspend network work while the tab is hidden. The existing busy flag
    // remains the no-overlap authority inside wbLivePollTick().
    let wbAutoPollId = null;
    let wbAutoPollStopped = false;
    const wbLivePollDelayMs = () => {
      if (document.hidden) return 15000;
      const autoOn = root.querySelector(
        "[data-wb-auto-attack][data-wb-auto-enabled='1']"
      );
      return autoOn ? 3000 : 7000;
    };
    const wbScheduleLivePoll = (delayMs = wbLivePollDelayMs()) => {
      if (wbAutoPollStopped || !root.isConnected) return;
      if (wbAutoPollId != null) clearTimeout(wbAutoPollId);
      wbAutoPollId = window.setTimeout(() => {
        wbAutoPollId = null;
        if (!document.hidden) wbLivePollTick();
        wbScheduleLivePoll();
      }, Math.max(250, Number(delayMs) || wbLivePollDelayMs()));
    };
    const wbHandleVisibilityChange = () => {
      if (wbAutoPollStopped) return;
      if (document.hidden) {
        wbScheduleLivePoll(15000);
        return;
      }
      // Refresh immediately after returning to the page, then resume adaptive cadence.
      wbLivePollTick();
      wbScheduleLivePoll(wbLivePollDelayMs());
    };
    document.addEventListener("visibilitychange", wbHandleVisibilityChange);
    wbScheduleLivePoll(1000);
    if (typeof GC.registerCleanup === "function") {
      GC.registerCleanup(() => {
        wbAutoPollStopped = true;
        document.removeEventListener("visibilitychange", wbHandleVisibilityChange);
        if (wbAutoPollId != null) clearTimeout(wbAutoPollId);
        wbAutoPollId = null;
      });
    }
'''

if new_guard not in text:
    if text.count(old_guard) != 1:
        raise SystemExit(f"expected one world-boss live poll guard block, found {text.count(old_guard)}")
    text = text.replace(old_guard, new_guard, 1)

if new_scheduler not in text:
    if text.count(old_scheduler) != 1:
        raise SystemExit(f"expected one legacy world-boss scheduler block, found {text.count(old_scheduler)}")
    text = text.replace(old_scheduler, new_scheduler, 1)

path.write_text(text, encoding="utf-8")
print("GC-PG-WB-POLL-001 materialized")
