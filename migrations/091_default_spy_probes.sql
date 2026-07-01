-- GC-977A: Configurable default Phantom Probe count for Galaxy quick spy.

ALTER TABLE users ADD COLUMN default_spy_probes INTEGER NOT NULL DEFAULT 5;
