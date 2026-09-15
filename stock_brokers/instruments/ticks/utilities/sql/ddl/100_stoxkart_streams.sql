CREATE SCHEMA IF NOT EXISTS "stoxkart";

CREATE TABLE IF NOT EXISTS stoxkart.ticks (
    time                timestamptz   not null,
    id                  text          not null,
    instrument_token    text,
    exchange            text,
    mode                text,
    last_price          numeric(18,4),
    last_quantity       bigint,
    average_price       numeric(18,4),
    volume              bigint,
    buy_quantity        bigint,
    sell_quantity       bigint,
    open                numeric(18,4),
    high                numeric(18,4),
    low                 numeric(18,4),
    close               numeric(18,4),
    change              numeric(12,6),
    oi                  bigint,
    oi_day_high         bigint,
    oi_day_low          bigint,
    last_trade_time     timestamptz,
    exchange_timestamp  timestamptz,
    bid1_price      numeric(18,4),
    bid1_quantity   bigint,
    bid1_orders     integer,
    bid2_price      numeric(18,4),
    bid2_quantity   bigint,
    bid2_orders     integer,
    bid3_price      numeric(18,4),
    bid3_quantity   bigint,
    bid3_orders     integer,
    bid4_price      numeric(18,4),
    bid4_quantity   bigint,
    bid4_orders     integer,
    bid5_price      numeric(18,4),
    bid5_quantity   bigint,
    bid5_orders     integer,
    ask1_price      numeric(18,4),
    ask1_quantity   bigint,
    ask1_orders     integer,
    ask2_price      numeric(18,4),
    ask2_quantity   bigint,
    ask2_orders     integer,
    ask3_price      numeric(18,4),
    ask3_quantity   bigint,
    ask3_orders     integer,
    ask4_price      numeric(18,4),
    ask4_quantity   bigint,
    ask4_orders     integer,
    ask5_price      numeric(18,4),
    ask5_quantity   bigint,
    ask5_orders     integer
);

SELECT create_hypertable(
    'stoxkart.ticks',
    by_range('time', INTERVAL '1 day'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS ticks_id_time_idx
    ON stoxkart.ticks (id, "time" DESC);

ALTER TABLE stoxkart.ticks SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'id',
    timescaledb.orderby = '"time" DESC'
);

CALL add_columnstore_policy(
    'stoxkart.ticks',
    after => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE TABLE IF NOT EXISTS stoxkart.order_updates (
    time                timestamptz   not null,
    order_id            text          not null,
    exchange_order_id   text,
    parent_order_id     text,
    status              text,
    status_message      text,
    id                  text,
    instrument_token    text,
    tradingsymbol       text,
    exchange            text,
    transaction_type    text,
    product             text,
    order_type          text,
    validity            text,
    quantity            bigint,
    filled_quantity     bigint,
    pending_quantity    bigint,
    cancelled_quantity  bigint,
    disclosed_quantity  bigint,
    price               numeric(18,4),
    trigger_price       numeric(18,4),
    average_price       numeric(18,4),
    order_timestamp     timestamptz,
    exchange_timestamp  timestamptz,
    tag                 text,
    raw                 jsonb
);

SELECT create_hypertable(
    'stoxkart.order_updates',
    by_range('time', INTERVAL '1 day'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS order_updates_order_time_idx
    ON stoxkart.order_updates (order_id, "time" DESC);

CREATE INDEX IF NOT EXISTS order_updates_status_time_idx
    ON stoxkart.order_updates (status, "time" DESC);

ALTER TABLE stoxkart.order_updates SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'order_id',
    timescaledb.orderby = '"time" DESC'
);

CALL add_columnstore_policy(
    'stoxkart.order_updates',
    after => INTERVAL '7 days',
    if_not_exists => TRUE
);
