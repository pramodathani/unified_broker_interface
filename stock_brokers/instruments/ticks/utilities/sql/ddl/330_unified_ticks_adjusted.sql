-- Reading unified.ticks adjusted for splits, bonuses and demergers.
--
-- Stored prices stay as streamed, and every confirmed factor whose ex-date falls after the tick's trading day is applied
-- on read, through unified.adjustment_ranges. That view is created by the historical DDL (240), so this file is applied after it, by
-- bin/unified/historical_prices, together with 300_unified_ticks.sql for the table it reads; bin/unified/persist_ticks
-- applies only 300 and never needs this.
--
-- Prices are multiplied by price_factor and every quantity except open interest by volume_factor. Open interest is left
-- alone: derivatives are not adjusted, and a cash instrument has no open interest. Instruments with no factors pass
-- through the LEFT JOIN unchanged.

CREATE OR REPLACE VIEW unified.ticks_adjusted AS
SELECT t."time",
       t.instrument_id,
       t.broker,
       t.exchange_time,
       t.last_trade_time,
       round(t.last_price     * coalesce(r.price_factor, 1), 4)          AS last_price,
       round(t.last_quantity  * coalesce(r.volume_factor, 1))::bigint    AS last_quantity,
       round(t.average_price  * coalesce(r.price_factor, 1), 4)          AS average_price,
       round(t.volume         * coalesce(r.volume_factor, 1))::bigint    AS volume,
       round(t.buy_quantity   * coalesce(r.volume_factor, 1))::bigint    AS buy_quantity,
       round(t.sell_quantity  * coalesce(r.volume_factor, 1))::bigint    AS sell_quantity,
       round(t.open           * coalesce(r.price_factor, 1), 4)          AS open,
       round(t.high           * coalesce(r.price_factor, 1), 4)          AS high,
       round(t.low            * coalesce(r.price_factor, 1), 4)          AS low,
       round(t.previous_close * coalesce(r.price_factor, 1), 4)          AS previous_close,
       t.change_percent,
       t.oi,
       t.oi_day_high,
       t.oi_day_low,
       t.lot_size,
       round(t.bid1_price * coalesce(r.price_factor, 1), 4)              AS bid1_price,
       round(t.bid1_quantity * coalesce(r.volume_factor, 1))::bigint     AS bid1_quantity,
       t.bid1_orders,
       round(t.bid2_price * coalesce(r.price_factor, 1), 4)              AS bid2_price,
       round(t.bid2_quantity * coalesce(r.volume_factor, 1))::bigint     AS bid2_quantity,
       t.bid2_orders,
       round(t.bid3_price * coalesce(r.price_factor, 1), 4)              AS bid3_price,
       round(t.bid3_quantity * coalesce(r.volume_factor, 1))::bigint     AS bid3_quantity,
       t.bid3_orders,
       round(t.bid4_price * coalesce(r.price_factor, 1), 4)              AS bid4_price,
       round(t.bid4_quantity * coalesce(r.volume_factor, 1))::bigint     AS bid4_quantity,
       t.bid4_orders,
       round(t.bid5_price * coalesce(r.price_factor, 1), 4)              AS bid5_price,
       round(t.bid5_quantity * coalesce(r.volume_factor, 1))::bigint     AS bid5_quantity,
       t.bid5_orders,
       round(t.ask1_price * coalesce(r.price_factor, 1), 4)              AS ask1_price,
       round(t.ask1_quantity * coalesce(r.volume_factor, 1))::bigint     AS ask1_quantity,
       t.ask1_orders,
       round(t.ask2_price * coalesce(r.price_factor, 1), 4)              AS ask2_price,
       round(t.ask2_quantity * coalesce(r.volume_factor, 1))::bigint     AS ask2_quantity,
       t.ask2_orders,
       round(t.ask3_price * coalesce(r.price_factor, 1), 4)              AS ask3_price,
       round(t.ask3_quantity * coalesce(r.volume_factor, 1))::bigint     AS ask3_quantity,
       t.ask3_orders,
       round(t.ask4_price * coalesce(r.price_factor, 1), 4)              AS ask4_price,
       round(t.ask4_quantity * coalesce(r.volume_factor, 1))::bigint     AS ask4_quantity,
       t.ask4_orders,
       round(t.ask5_price * coalesce(r.price_factor, 1), 4)              AS ask5_price,
       round(t.ask5_quantity * coalesce(r.volume_factor, 1))::bigint     AS ask5_quantity,
       t.ask5_orders,
       coalesce(r.price_factor, 1)                                       AS price_factor
FROM unified.ticks t
LEFT JOIN unified.adjustment_ranges r
       ON r.instrument_id = t.instrument_id
      AND t."time" >= r.valid_from
      AND t."time" <  r.valid_to;
