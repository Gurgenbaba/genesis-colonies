-- 166_pg_money_amounts_numeric.sql
-- GC-BACKEND: postgres
-- P0-B1: resource-denominated auction + alliance money domains become
-- exact, unconstrained PostgreSQL NUMERIC.

ALTER TABLE auction_house_listings
    ALTER COLUMN start_price DROP DEFAULT;
ALTER TABLE auction_house_listings
    ALTER COLUMN start_price TYPE NUMERIC USING TRUNC(start_price::numeric);

ALTER TABLE auction_house_listings
    ALTER COLUMN current_bid DROP DEFAULT;
ALTER TABLE auction_house_listings
    ALTER COLUMN current_bid TYPE NUMERIC USING TRUNC(current_bid::numeric);
ALTER TABLE auction_house_listings
    ALTER COLUMN current_bid SET DEFAULT 0;

ALTER TABLE auction_house_bids
    ALTER COLUMN amount TYPE NUMERIC USING TRUNC(amount::numeric);

ALTER TABLE alliances
    ALTER COLUMN pool_metal DROP DEFAULT;
ALTER TABLE alliances
    ALTER COLUMN pool_metal TYPE NUMERIC USING TRUNC(pool_metal::numeric);
ALTER TABLE alliances
    ALTER COLUMN pool_metal SET DEFAULT 0;

ALTER TABLE alliances
    ALTER COLUMN pool_crystal DROP DEFAULT;
ALTER TABLE alliances
    ALTER COLUMN pool_crystal TYPE NUMERIC USING TRUNC(pool_crystal::numeric);
ALTER TABLE alliances
    ALTER COLUMN pool_crystal SET DEFAULT 0;

ALTER TABLE alliances
    ALTER COLUMN pool_fuel_cells DROP DEFAULT;
ALTER TABLE alliances
    ALTER COLUMN pool_fuel_cells TYPE NUMERIC USING TRUNC(pool_fuel_cells::numeric);
ALTER TABLE alliances
    ALTER COLUMN pool_fuel_cells SET DEFAULT 0;

ALTER TABLE alliance_donations
    ALTER COLUMN amount TYPE NUMERIC USING TRUNC(amount::numeric);

ALTER TABLE alliance_projects
    ALTER COLUMN cost_metal DROP DEFAULT;
ALTER TABLE alliance_projects
    ALTER COLUMN cost_metal TYPE NUMERIC USING TRUNC(cost_metal::numeric);
ALTER TABLE alliance_projects
    ALTER COLUMN cost_metal SET DEFAULT 0;

ALTER TABLE alliance_projects
    ALTER COLUMN cost_crystal DROP DEFAULT;
ALTER TABLE alliance_projects
    ALTER COLUMN cost_crystal TYPE NUMERIC USING TRUNC(cost_crystal::numeric);
ALTER TABLE alliance_projects
    ALTER COLUMN cost_crystal SET DEFAULT 0;

ALTER TABLE alliance_projects
    ALTER COLUMN cost_fuel_cells DROP DEFAULT;
ALTER TABLE alliance_projects
    ALTER COLUMN cost_fuel_cells TYPE NUMERIC USING TRUNC(cost_fuel_cells::numeric);
ALTER TABLE alliance_projects
    ALTER COLUMN cost_fuel_cells SET DEFAULT 0;
