"""
`/api/orders`: today's orders and trades across every broker, and placing and cancelling an order.

| Route | Does |
| --- | --- |
| `GET /details` | Every broker's orders, from `unified:orders:orders`, kept by `bin/unified/orders` every half second |
| `GET /trades` | Every broker's trades, from `unified:orders:trades`, kept by `bin/unified/trades` every half second |
| `POST /place` | Places one order at the next broker in a round robin, reading only Redis before the broker's place-order call |
| `DELETE /cancel` | Cancels one order at the broker whose order book in Redis holds its order id |

`GET /details` and `GET /trades` ask no broker. `POST /place` and `DELETE /cancel` each send exactly one request to one broker and never read MongoDB or PostgreSQL, so that the API's own work adds as little as possible to the time the broker takes.
"""

import datetime
import decimal
import hmac
import json
import re
import threading
import time
import uuid

import redis
import requests
from flask import jsonify, request

from unified_broker_interface.blueprints.base import BaseBlueprint, authenticated
from unified_broker_interface.utilities.unified_documents import read_document
from utilities.configurations import api_configuration


class OrdersBlueprint(BaseBlueprint):
    """The `/api/orders` routes: order and trade books from Redis, and placing and cancelling orders.

    Attributes:
        broker_sessions (dict): One `requests.Session` per broker name, created on the first order or cancel sent to that broker, so later requests reuse its open connection.
        broker_sessions_lock (threading.Lock): Guards the creation of entries in `broker_sessions` across the worker's threads.
    """

    name = 'orders'
    routes = [
        ('/details', 'details', ['GET']),
        ('/trades', 'trades', ['GET']),
        ('/place', 'place', ['POST']),
        ('/cancel', 'cancel', ['DELETE']),
    ]

    def __init__(self):
        """Builds the blueprint with no broker connections open yet.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.broker_sessions = {}
        self.broker_sessions_lock = threading.Lock()

    @authenticated
    def details(self):
        """Answers today's orders at every broker, with how each broker's data was read.

        See `utilities/unified_documents.py` for when the document is not served.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).
        """
        body, status = read_document(
            self.cache,
            'unified:orders:orders',
            30,
            'orders',
        )
        return jsonify(body), status

    @authenticated
    def trades(self):
        """Answers today's trades at every broker, with how each broker's data was read.

        See `utilities/unified_documents.py` for when the document is not served.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).
        """
        body, status = read_document(
            self.cache,
            'unified:orders:trades',
            30,
            'trades',
        )
        return jsonify(body), status

    def place(self):
        """Places one order at the next broker in the round robin.

        The JSON body names the instrument by `instrument_id`, or by `exchange`, `segment` and the segment's identity fields (`symbol`, or `underlying_symbol` and `expiry_date`, and for an option `strike_price` and `option_type`).
        It gives `transaction_type` (BUY or SELL), `product` (CNC, MIS or NRML), `order_type` (MARKET, LIMIT, SL or SL-M) and `quantity` in units.
        It may give `validity` (DAY or IOC, default DAY), `price`, `trigger_price`, `disclosed_quantity`, `after_market`, `tag` and `dry_run`.

        The method reads Redis in two or three round trips and then sends one request to one broker.
        It never reads MongoDB or PostgreSQL, never calls a broker for anything but the order itself, and never retries a sent order at another broker.
        With `dry_run` it answers with the request it would have sent instead of sending it.
        Every failure is answered with an HTTP status rather than raised.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int), which is 200 when the broker accepted the order or for a dry run, 422 when the broker refused it, 504 when the outcome is unknown, 400 for an order that is not valid, 401 for a missing, wrong or expired access token, 404 for an instrument that is not mapped, and 503 when Redis cannot be read or no broker can take the order.
        """
        started_at = time.perf_counter()

        access_token = request.headers.get('access-token')
        if not access_token:
            return jsonify({'error': 'Access token is required'}), 401

        broker_names = [
            'dhan',
            'flattrade',
            'fyers',
            'groww',
            'indmoney',
            'kotak',
            'shoonya',
            'stoxkart',
            'wisdom_capital',
            'zerodha',
        ]

        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.hget('last_login', 'unified_broker_interface')
            pipeline.get('unified:catalogue:current_date')
            pipeline.hmget('last_login', broker_names)
            pipeline.hmget('settings', broker_names)
            first_replies = pipeline.execute()
        except redis.RedisError as error:
            return jsonify({'error': f'Redis could not be read: {error}'}), 503
        token_document_text = first_replies[0]
        mapping_date_text = first_replies[1]
        login_texts = first_replies[2]
        settings_texts = first_replies[3]

        token_document = None
        if token_document_text:
            try:
                token_document = json.loads(token_document_text)
            except ValueError:
                token_document = None
        stored_token = None
        if isinstance(token_document, dict):
            stored_token = token_document.get('access_token')
        if not stored_token or not hmac.compare_digest(
            access_token.encode(),
            str(stored_token).encode(),
        ):
            return jsonify({'error': 'Invalid access token'}), 401
        try:
            expires_at = datetime.datetime.strptime(
                token_document['expires_at'],
                '%Y-%m-%d %H:%M:%S.%f',
            )
        except (KeyError, TypeError, ValueError):
            expires_at = None
        if expires_at is None or expires_at <= datetime.datetime.now():
            return jsonify({'error': 'Access token has expired'}), 401

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            message = 'the request body must be a JSON object'
            return jsonify({'error': message}), 400

        transaction_type = str(body.get('transaction_type') or '')
        transaction_type = transaction_type.strip().upper()
        if transaction_type not in (
            'BUY',
            'SELL',
        ):
            message = 'transaction_type must be one of BUY, SELL'
            return jsonify({'error': message}), 400

        product = str(body.get('product') or '').strip().upper()
        if product not in (
            'CNC',
            'MIS',
            'NRML',
        ):
            message = 'product must be one of CNC, MIS, NRML'
            return jsonify({'error': message}), 400

        order_type = str(body.get('order_type') or '').strip().upper()
        if order_type not in (
            'MARKET',
            'LIMIT',
            'SL',
            'SL-M',
        ):
            message = 'order_type must be one of MARKET, LIMIT, SL, SL-M'
            return jsonify({'error': message}), 400

        validity = str(body.get('validity') or 'DAY').strip().upper()
        if validity not in (
            'DAY',
            'IOC',
        ):
            message = 'validity must be one of DAY, IOC'
            return jsonify({'error': message}), 400

        whole_numbers = {}
        for field_name in (
            'quantity',
            'disclosed_quantity',
        ):
            raw_value = body.get(field_name)
            minimum = 1 if field_name == 'quantity' else 0
            if raw_value is None or raw_value == '':
                if field_name == 'quantity':
                    message = 'quantity is required'
                    return jsonify({'error': message}), 400
                whole_numbers[field_name] = 0
                continue
            try:
                value = decimal.Decimal(str(raw_value).strip())
            except decimal.InvalidOperation:
                value = None
            if (
                value is None
                or not value.is_finite()
                or value != value.to_integral_value()
                or value < minimum
            ):
                message = (
                    f'{field_name} must be a whole number of at least {minimum}'
                )
                return jsonify({'error': message}), 400
            whole_numbers[field_name] = int(value)
        quantity = whole_numbers['quantity']
        disclosed_quantity = whole_numbers['disclosed_quantity']
        if disclosed_quantity > quantity:
            message = 'disclosed_quantity cannot be more than quantity'
            return jsonify({'error': message}), 400

        prices = {}
        for field_name in (
            'price',
            'trigger_price',
        ):
            raw_value = body.get(field_name)
            if raw_value is None or raw_value == '':
                prices[field_name] = None
                continue
            try:
                value = decimal.Decimal(str(raw_value).strip())
            except decimal.InvalidOperation:
                value = None
            if value is None or not value.is_finite() or value < 0:
                message = f'{field_name} must be a number of at least 0'
                return jsonify({'error': message}), 400
            prices[field_name] = value
        price = prices['price']
        trigger_price = prices['trigger_price']

        priced_order_types = [
            'LIMIT',
            'SL',
        ]
        triggered_order_types = [
            'SL',
            'SL-M',
        ]
        if order_type in priced_order_types and not price:
            message = f'a {order_type} order needs a price'
            return jsonify({'error': message}), 400
        if order_type not in priced_order_types and price:
            message = f'a {order_type} order takes no price'
            return jsonify({'error': message}), 400
        if order_type in triggered_order_types and not trigger_price:
            message = f'a {order_type} order needs a trigger_price'
            return jsonify({'error': message}), 400
        if order_type not in triggered_order_types and trigger_price:
            message = f'a {order_type} order takes no trigger_price'
            return jsonify({'error': message}), 400

        true_spellings = [
            'true',
            '1',
            'yes',
        ]
        false_spellings = [
            'false',
            '0',
            'no',
            '',
        ]
        flags = {}
        for field_name in (
            'after_market',
            'dry_run',
        ):
            raw_value = body.get(field_name)
            if raw_value is None:
                flags[field_name] = False
            elif isinstance(raw_value, bool):
                flags[field_name] = raw_value
            elif str(raw_value).strip().lower() in true_spellings:
                flags[field_name] = True
            elif str(raw_value).strip().lower() in false_spellings:
                flags[field_name] = False
            else:
                message = f'{field_name} must be true or false'
                return jsonify({'error': message}), 400
        after_market = flags['after_market']
        dry_run = flags['dry_run']

        tag = body.get('tag')
        if tag is None or tag == '':
            tag = None
        elif not isinstance(tag, str):
            message = 'tag must be 1 to 20 letters and digits'
            return jsonify({'error': message}), 400
        else:
            tag = tag.strip()
            if not re.fullmatch(r'[A-Za-z0-9]{1,20}', tag):
                message = 'tag must be 1 to 20 letters and digits'
                return jsonify({'error': message}), 400

        tradeable_segments = {
            'equities': 'security',
            'equity_futures': 'future',
            'equity_options': 'option',
            'equity_index_futures': 'future',
            'equity_index_options': 'option',
            'fixed_income': 'security',
            'fixed_income_futures': 'future',
            'fixed_income_options': 'option',
            'fixed_income_index_futures': 'future',
            'fixed_income_index_options': 'option',
            'exchange_traded_funds': 'security',
            'investment_trusts': 'security',
            'mutual_funds': 'security',
        }

        instrument_id = None
        catalogue_segment = None
        catalogue_prefix = None
        raw_instrument_id = body.get('instrument_id')
        if raw_instrument_id:
            try:
                instrument_id = str(uuid.UUID(str(raw_instrument_id).strip()))
            except ValueError:
                message = 'instrument_id must be a UUID'
                return jsonify({'error': message}), 400
        else:
            exchange = str(body.get('exchange') or '').strip().lower()
            if exchange not in (
                'nse',
                'bse',
            ):
                message = (
                    'give instrument_id, or an exchange of nse or bse with a segment and its identity fields'
                )
                return jsonify({'error': message}), 400
            bare_segment = str(body.get('segment') or '').strip().lower()
            if bare_segment.startswith(exchange + '_'):
                bare_segment = bare_segment[len(exchange) + 1:]
            if bare_segment not in tradeable_segments:
                message = (
                    f'orders are not sent for the segment {body.get("segment")!r}'
                )
                return jsonify({'error': message}), 400
            shape = tradeable_segments[bare_segment]
            catalogue_segment = f'{exchange}_{bare_segment}'

            if shape == 'security':
                symbol = str(body.get('symbol') or '').strip().upper()
                if not symbol:
                    message = 'a security segment needs symbol'
                    return jsonify({'error': message}), 400
                catalogue_prefix = symbol.replace('|', '/') + '|'
            else:
                underlying_symbol = str(body.get('underlying_symbol') or '')
                underlying_symbol = underlying_symbol.strip().upper()
                expiry_text = str(body.get('expiry_date') or '').strip()
                if not underlying_symbol or not expiry_text:
                    message = (
                        f'a {shape} segment needs underlying_symbol and expiry_date'
                    )
                    return jsonify({'error': message}), 400
                try:
                    expiry_date = datetime.date.fromisoformat(expiry_text)
                except ValueError:
                    message = 'expiry_date must be a date in YYYY-MM-DD format'
                    return jsonify({'error': message}), 400
                catalogue_prefix = (
                    underlying_symbol.replace('|', '/')
                    + '|'
                    + expiry_date.isoformat()
                    + '|'
                )

            if shape == 'option':
                strike_text = str(body.get('strike_price') or '').strip()
                option_type = str(body.get('option_type') or '')
                option_type = option_type.strip().upper()
                try:
                    strike_price = decimal.Decimal(strike_text)
                except decimal.InvalidOperation:
                    strike_price = None
                if strike_price is None or not strike_price.is_finite():
                    message = 'an option segment needs a numeric strike_price'
                    return jsonify({'error': message}), 400
                if option_type not in (
                    'CE',
                    'PE',
                ):
                    message = 'option_type must be CE or PE'
                    return jsonify({'error': message}), 400
                catalogue_prefix = (
                    catalogue_prefix
                    + f'{strike_price:016.4f}'
                    + '|'
                    + option_type
                    + '|'
                )

        excluded_brokers = api_configuration['order_excluded_brokers']
        rotation = []
        for broker_name in broker_names:
            if broker_name not in excluded_brokers:
                rotation.append(broker_name)
        if not rotation:
            message = 'every broker is excluded from order placement'
            return jsonify({'error': message}), 503

        if not mapping_date_text:
            message = 'no instruments have been mapped yet'
            return jsonify({'error': message}), 503
        catalogue_key_prefix = f'unified:catalogue:{mapping_date_text}:'

        if instrument_id is None:
            catalogue_key = (
                catalogue_key_prefix + 'catalogue:' + catalogue_segment
            )
            prefix_bytes = catalogue_prefix.encode()
            try:
                members = self.cache.zrangebylex(
                    catalogue_key,
                    b'[' + prefix_bytes,
                    b'(' + prefix_bytes + b'\xff',
                    start=0,
                    num=2,
                )
            except redis.RedisError as error:
                message = f'Redis could not be read: {error}'
                return jsonify({'error': message}), 503
            if not members:
                message = 'the instrument is not mapped'
                return jsonify({'error': message}), 404
            if len(members) > 1:
                message = (
                    'the identity fields match more than one instrument, so give instrument_id'
                )
                return jsonify({'error': message}), 400
            instrument_id = str(members[0]).rsplit('|', 1)[1]

        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.hget(catalogue_key_prefix + 'identity', instrument_id)
            pipeline.hget(catalogue_key_prefix + 'order_handles', instrument_id)
            pipeline.incr('unified:orders:round_robin')
            second_replies = pipeline.execute()
        except redis.RedisError as error:
            return jsonify({'error': f'Redis could not be read: {error}'}), 503
        identity_text = second_replies[0]
        handles_text = second_replies[1]
        round_robin_counter = second_replies[2]

        identity = None
        handles = None
        try:
            if identity_text:
                identity = json.loads(identity_text)
            if handles_text:
                handles = json.loads(handles_text)
        except ValueError:
            identity = None
            handles = None
        if not isinstance(identity, dict) or not isinstance(handles, dict):
            message = 'the instrument is not mapped'
            return jsonify({'error': message}), 404

        instrument_segment = str(identity.get('segment') or '')
        instrument_exchange, _, instrument_bare_segment = (
            instrument_segment.partition('_')
        )
        tradeable_exchanges = [
            'nse',
            'bse',
        ]
        if (
            instrument_exchange not in tradeable_exchanges
            or instrument_bare_segment not in tradeable_segments
        ):
            message = f'orders are not sent for {instrument_segment} instruments'
            return jsonify({'error': message}), 400
        if tradeable_segments[instrument_bare_segment] == 'security':
            instrument_kind = 'cash'
        else:
            instrument_kind = 'derivative'

        identifier_fields = {
            'dhan': 'broker_token',
            'flattrade': 'order_symbol',
            'fyers': 'order_symbol',
            'groww': 'order_symbol',
            'indmoney': 'broker_token',
            'kotak': 'order_symbol',
            'shoonya': 'order_symbol',
            'stoxkart': 'broker_token',
            'wisdom_capital': 'broker_token',
            'zerodha': 'order_symbol',
        }
        settings_fields = {
            'dhan': [
                'client_id',
            ],
            'flattrade': [
                'username',
            ],
            'fyers': [
                'app_id',
            ],
            'groww': [],
            'indmoney': [],
            'kotak': [],
            'shoonya': [
                'ucc_code',
            ],
            'stoxkart': [
                'ucc_code',
                'api_key',
            ],
            'wisdom_capital': [
                'ucc_code',
            ],
            'zerodha': [
                'api_key',
            ],
        }

        brokers_without_after_market = [
            'groww',
            'wisdom_capital',
        ]

        skipped = []
        chosen_broker = None
        chosen_handle = None
        chosen_login = None
        chosen_settings = None
        start_index = round_robin_counter % len(rotation)
        for offset in range(len(rotation)):
            broker_name = rotation[(start_index + offset) % len(rotation)]
            position = broker_names.index(broker_name)

            handle = handles.get(broker_name)
            if not isinstance(handle, dict):
                skipped.append({
                    'broker': broker_name,
                    'reason': 'has no mapping for the instrument',
                })
                continue
            identifier_field = identifier_fields[broker_name]
            if not handle.get(identifier_field):
                skipped.append({
                    'broker': broker_name,
                    'reason': f'its mapping carries no {identifier_field}',
                })
                continue
            if (
                broker_name == 'wisdom_capital'
                and not str(handle.get('broker_token')).isdigit()
            ):
                skipped.append({
                    'broker': broker_name,
                    'reason': 'its mapping carries no numeric instrument id',
                })
                continue

            login = None
            if login_texts[position]:
                try:
                    login = json.loads(login_texts[position])
                except ValueError:
                    login = None
            if not isinstance(login, dict) or not login.get('access_token'):
                skipped.append({
                    'broker': broker_name,
                    'reason': 'has no login in Redis',
                })
                continue
            if broker_name == 'kotak' and not login.get('sid'):
                skipped.append({
                    'broker': broker_name,
                    'reason': 'its login in Redis carries no sid',
                })
                continue

            broker_settings = {}
            if settings_texts[position]:
                try:
                    broker_settings = json.loads(settings_texts[position])
                except ValueError:
                    broker_settings = {}
            if not isinstance(broker_settings, dict):
                broker_settings = {}
            missing_settings = []
            for settings_field in settings_fields[broker_name]:
                if not broker_settings.get(settings_field):
                    missing_settings.append(settings_field)
            if missing_settings:
                skipped.append({
                    'broker': broker_name,
                    'reason': (
                        'has no ' + ', '.join(missing_settings) + ' in its Redis settings'
                    ),
                })
                continue

            if (
                broker_name == 'indmoney'
                and order_type in triggered_order_types
            ):
                skipped.append({
                    'broker': broker_name,
                    'reason': f'takes no {order_type} orders',
                })
                continue
            if after_market and broker_name in brokers_without_after_market:
                skipped.append({
                    'broker': broker_name,
                    'reason': 'takes no after-market orders',
                })
                continue

            chosen_broker = broker_name
            chosen_handle = handle
            chosen_login = login
            chosen_settings = broker_settings
            break

        if chosen_broker is None:
            return jsonify({
                'error': 'no broker can take this order',
                'instrument_id': instrument_id,
                'skipped': skipped,
            }), 503

        try:
            lot_size = decimal.Decimal(str(chosen_handle.get('lot_size')))
        except decimal.InvalidOperation:
            lot_size = None
        if (
            lot_size is not None
            and lot_size.is_finite()
            and lot_size > 0
            and decimal.Decimal(quantity) % lot_size != 0
        ):
            lot_text = format(lot_size.normalize(), 'f')
            message = f'quantity must be a whole number of lots of {lot_text}'
            return jsonify({'error': message}), 400

        tick_size_counts = {}
        for broker_handle in handles.values():
            if not isinstance(broker_handle, dict):
                continue
            try:
                tick_size = decimal.Decimal(str(broker_handle.get('tick_size')))
            except decimal.InvalidOperation:
                continue
            if tick_size.is_finite() and tick_size > 0:
                count = tick_size_counts.get(tick_size, 0)
                tick_size_counts[tick_size] = count + 1
        agreed_tick_size = None
        highest_count = 0
        tied = False
        for tick_size, count in tick_size_counts.items():
            if count > highest_count:
                agreed_tick_size = tick_size
                highest_count = count
                tied = False
            elif count == highest_count:
                tied = True
        if tied:
            agreed_tick_size = None
        if agreed_tick_size is not None:
            for field_name in (
                'price',
                'trigger_price',
            ):
                value = prices[field_name]
                if value and value % agreed_tick_size != 0:
                    tick_text = format(agreed_tick_size.normalize(), 'f')
                    message = (
                        f'{field_name} must be a whole number of ticks of {tick_text}'
                    )
                    return jsonify({'error': message}), 400

        broker_token = str(chosen_handle.get('broker_token'))
        order_symbol = chosen_handle.get('order_symbol')
        login_token = str(chosen_login.get('access_token'))
        price_text = str(price or 0)
        trigger_price_text = str(trigger_price or 0)
        price_number = float(price or 0)
        trigger_price_number = float(trigger_price or 0)
        broker_tag = tag
        request_url = None
        request_headers = {}
        request_data = None
        request_json = None
        shown_form = None
        verify_certificate = True

        if chosen_broker == 'zerodha':
            exchange_codes = {
                ('nse', 'cash'): 'NSE',
                ('bse', 'cash'): 'BSE',
                ('nse', 'derivative'): 'NFO',
                ('bse', 'derivative'): 'BFO',
            }
            variety = 'amo' if after_market else 'regular'
            request_url = f'https://api.kite.trade/orders/{variety}'
            request_headers = {
                'X-Kite-Version': '3',
                'Authorization': (
                    f'token {chosen_settings["api_key"]}:{login_token}'
                ),
            }
            request_data = {
                'tradingsymbol': order_symbol,
                'exchange': exchange_codes[
                    (instrument_exchange, instrument_kind)
                ],
                'transaction_type': transaction_type,
                'order_type': order_type,
                'quantity': quantity,
                'product': product,
                'validity': validity,
                'price': price_text,
                'trigger_price': trigger_price_text,
                'disclosed_quantity': disclosed_quantity,
            }
            if tag:
                request_data['tag'] = tag
            shown_form = request_data

        elif chosen_broker == 'dhan':
            segment_codes = {
                ('nse', 'cash'): 'NSE_EQ',
                ('bse', 'cash'): 'BSE_EQ',
                ('nse', 'derivative'): 'NSE_FNO',
                ('bse', 'derivative'): 'BSE_FNO',
            }
            order_type_codes = {
                'MARKET': 'MARKET',
                'LIMIT': 'LIMIT',
                'SL': 'STOP_LOSS',
                'SL-M': 'STOP_LOSS_MARKET',
            }
            product_codes = {
                'CNC': 'CNC',
                'MIS': 'INTRADAY',
                'NRML': 'MARGIN',
            }
            request_url = 'https://api.dhan.co/v2/orders'
            request_headers = {
                'access-token': login_token,
            }
            request_json = {
                'dhanClientId': str(chosen_settings['client_id']),
                'transactionType': transaction_type,
                'exchangeSegment': segment_codes[
                    (instrument_exchange, instrument_kind)
                ],
                'productType': product_codes[product],
                'orderType': order_type_codes[order_type],
                'validity': validity,
                'securityId': broker_token,
                'quantity': quantity,
                'disclosedQuantity': disclosed_quantity,
                'price': price_number,
                'triggerPrice': trigger_price_number,
                'afterMarketOrder': after_market,
            }
            if after_market:
                request_json['amoTime'] = 'OPEN'
            if tag:
                request_json['correlationId'] = tag

        elif chosen_broker == 'fyers':
            order_type_codes = {
                'LIMIT': 1,
                'MARKET': 2,
                'SL-M': 3,
                'SL': 4,
            }
            side_codes = {
                'BUY': 1,
                'SELL': -1,
            }
            product_codes = {
                'CNC': 'CNC',
                'MIS': 'INTRADAY',
                'NRML': 'MARGIN',
            }
            request_url = 'https://api-t1.fyers.in/api/v3/orders/sync'
            request_headers = {
                'Authorization': f'{chosen_settings["app_id"]}:{login_token}',
            }
            request_json = {
                'symbol': order_symbol,
                'qty': quantity,
                'type': order_type_codes[order_type],
                'side': side_codes[transaction_type],
                'productType': product_codes[product],
                'limitPrice': price_number,
                'stopPrice': trigger_price_number,
                'validity': validity,
                'disclosedQty': disclosed_quantity,
                'offlineOrder': after_market,
            }
            if tag:
                request_json['orderTag'] = tag

        elif chosen_broker == 'groww':
            segment_codes = {
                ('nse', 'cash'): 'CASH',
                ('bse', 'cash'): 'CASH',
                ('nse', 'derivative'): 'FNO',
                ('bse', 'derivative'): 'FNO',
            }
            order_type_codes = {
                'MARKET': 'MARKET',
                'LIMIT': 'LIMIT',
                'SL': 'SL',
                'SL-M': 'SL_M',
            }
            broker_tag = f'{(tag or "ubi")[:7]}-{uuid.uuid4().hex[:12]}'
            request_url = 'https://api.groww.in/v1/order/create'
            request_headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {login_token}',
                'X-API-Version': '1.0',
            }
            request_json = {
                'trading_symbol': order_symbol,
                'quantity': quantity,
                'price': price_number,
                'trigger_price': trigger_price_number,
                'validity': validity,
                'exchange': instrument_exchange.upper(),
                'segment': segment_codes[
                    (instrument_exchange, instrument_kind)
                ],
                'product': product,
                'order_type': order_type_codes[order_type],
                'transaction_type': transaction_type,
                'order_reference_id': broker_tag,
            }

        elif chosen_broker == 'indmoney':
            segment_codes = {
                ('nse', 'cash'): 'EQUITY',
                ('bse', 'cash'): 'EQUITY',
                ('nse', 'derivative'): 'DERIVATIVE',
                ('bse', 'derivative'): 'DERIVATIVE',
            }
            product_codes = {
                'CNC': 'CNC',
                'MIS': 'INTRADAY',
                'NRML': 'MARGIN',
            }
            algo_identifiers = {
                'nse': '99999',
                'bse': '9999999999999999',
            }
            request_url = 'https://api.indstocks.com/order'
            request_headers = {
                'Authorization': login_token,
            }
            request_json = {
                'txn_type': transaction_type,
                'exchange': instrument_exchange.upper(),
                'segment': segment_codes[
                    (instrument_exchange, instrument_kind)
                ],
                'product': product_codes[product],
                'order_type': order_type,
                'validity': validity,
                'security_id': broker_token,
                'qty': quantity,
                'algo_id': algo_identifiers[instrument_exchange],
                'limit_price': price_number,
                'is_amo': after_market,
            }
            if tag:
                request_json['remarks'] = tag

        elif chosen_broker == 'kotak':
            segment_codes = {
                ('nse', 'cash'): 'nse_cm',
                ('bse', 'cash'): 'bse_cm',
                ('nse', 'derivative'): 'nse_fo',
                ('bse', 'derivative'): 'bse_fo',
            }
            order_type_codes = {
                'MARKET': 'MKT',
                'LIMIT': 'L',
                'SL': 'SL',
                'SL-M': 'SL-M',
            }
            side_codes = {
                'BUY': 'B',
                'SELL': 'S',
            }
            base_url = str(chosen_login.get('base_url') or '').strip()
            base_url = base_url.rstrip('/')
            if not base_url or base_url == 'None':
                base_url = 'https://gw-napi.kotaksecurities.com'
            elif not base_url.startswith((
                'http://',
                'https://',
            )):
                base_url = f'https://{base_url}'
            request_url = f'{base_url}/quick/order/rule/ms/place'
            request_headers = {
                'neo-fin-key': 'neotradeapi',
                'Auth': login_token,
                'Sid': str(chosen_login.get('sid')),
            }
            kotak_fields = {
                'es': segment_codes[(instrument_exchange, instrument_kind)],
                'ts': order_symbol,
                'qt': str(quantity),
                'pr': price_text,
                'tp': trigger_price_text,
                'dq': str(disclosed_quantity),
                'pc': product,
                'tt': side_codes[transaction_type],
                'pt': order_type_codes[order_type],
                'rt': validity,
                'mp': '0',
                'pf': 'N',
                'am': 'YES' if after_market else 'NO',
            }
            if tag:
                kotak_fields['rm'] = tag
            request_data = {
                'jData': json.dumps(kotak_fields),
            }
            shown_form = request_data

        elif chosen_broker == 'stoxkart':
            exchange_codes = {
                ('nse', 'cash'): 'NSE',
                ('bse', 'cash'): 'BSE',
                ('nse', 'derivative'): 'NFO',
                ('bse', 'derivative'): 'BFO',
            }
            order_type_codes = {
                'MARKET': 'MARKET',
                'LIMIT': 'LIMIT',
                'SL': 'STOPLOSS_LIMIT',
                'SL-M': 'STOPLOSS_MARKET',
            }
            product_codes = {
                'CNC': 'DELIVERY',
                'MIS': 'INTRADAY',
                'NRML': 'CARRYFORWARD',
            }
            variety = 'amo' if after_market else 'normal'
            request_url = f'https://openapi.stoxkart.com/orders/{variety}'
            request_headers = {
                'X-Client-Id': str(chosen_settings['ucc_code']),
                'X-Platform': 'api',
                'X-Api-Key': str(chosen_settings['api_key']),
                'X-Access-Token': login_token,
            }
            request_json = {
                'exchange': exchange_codes[
                    (instrument_exchange, instrument_kind)
                ],
                'token': broker_token,
                'action': transaction_type,
                'order_type': order_type_codes[order_type],
                'product_type': product_codes[product],
                'quantity': str(quantity),
                'disclose_quantity': str(disclosed_quantity),
                'price': price_text,
                'trigger_price': trigger_price_text,
                'stop_loss_price': trigger_price_text,
                'trailing_stop_loss': '0',
                'validity': validity,
                'algo_id': '0',
            }
            if tag:
                request_json['tag'] = tag

        elif chosen_broker == 'wisdom_capital':
            segment_codes = {
                ('nse', 'cash'): 'NSECM',
                ('bse', 'cash'): 'BSECM',
                ('nse', 'derivative'): 'NSEFO',
                ('bse', 'derivative'): 'BSEFO',
            }
            order_type_codes = {
                'MARKET': 'MARKET',
                'LIMIT': 'LIMIT',
                'SL': 'STOPLIMIT',
                'SL-M': 'STOPMARKET',
            }
            request_url = 'https://trade.wisdomcapital.in/interactive/orders'
            request_headers = {
                'authorization': login_token,
            }
            request_json = {
                'exchangeSegment': segment_codes[
                    (instrument_exchange, instrument_kind)
                ],
                'exchangeInstrumentID': int(broker_token),
                'productType': product,
                'orderType': order_type_codes[order_type],
                'orderSide': transaction_type,
                'timeInForce': validity,
                'disclosedQuantity': disclosed_quantity,
                'orderQuantity': quantity,
                'limitPrice': price_number,
                'stopPrice': trigger_price_number,
                'orderUniqueIdentifier': tag or 'ubi',
                'clientID': str(chosen_settings['ucc_code']),
            }
            verify_certificate = False

        else:
            exchange_codes = {
                ('nse', 'cash'): 'NSE',
                ('bse', 'cash'): 'BSE',
                ('nse', 'derivative'): 'NFO',
                ('bse', 'derivative'): 'BFO',
            }
            order_type_codes = {
                'MARKET': 'MKT',
                'LIMIT': 'LMT',
                'SL': 'SL-LMT',
                'SL-M': 'SL-MKT',
            }
            product_codes = {
                'CNC': 'C',
                'MIS': 'I',
                'NRML': 'M',
            }
            side_codes = {
                'BUY': 'B',
                'SELL': 'S',
            }
            if chosen_broker == 'flattrade':
                base_url = 'https://piconnect.flattrade.in/PiConnectAPI'
                account_identifier = str(chosen_settings['username'])
            else:
                base_url = 'https://api.shoonya.com/NorenWClientAPI'
                account_identifier = str(chosen_settings['ucc_code'])
            request_url = f'{base_url}/PlaceOrder'
            noren_fields = {
                'uid': account_identifier,
                'actid': account_identifier,
                'exch': exchange_codes[(instrument_exchange, instrument_kind)],
                'tsym': order_symbol,
                'qty': str(quantity),
                'prc': price_text,
                'trgprc': trigger_price_text,
                'dscqty': str(disclosed_quantity),
                'prd': product_codes[product],
                'trantype': side_codes[transaction_type],
                'prctyp': order_type_codes[order_type],
                'ret': validity,
                'ordersource': 'API',
                'amo': 'YES' if after_market else 'NO',
            }
            if tag:
                noren_fields['remarks'] = tag
            escaped_fields = json.dumps(noren_fields).replace('&', '\\u0026')
            request_data = f'jData={escaped_fields}&jKey={login_token}'
            shown_form = noren_fields

        if dry_run:
            shown_request = {
                'method': 'POST',
                'url': request_url,
            }
            if shown_form is not None:
                shown_request['form'] = shown_form
            else:
                shown_request['json'] = request_json
            preparation_milliseconds = (time.perf_counter() - started_at) * 1000
            return jsonify({
                'broker': chosen_broker,
                'instrument_id': instrument_id,
                'tag': broker_tag,
                'dry_run': True,
                'request': shown_request,
                'skipped': skipped,
                'timing_ms': {
                    'preparation': round(preparation_milliseconds, 3),
                },
            }), 200

        with self.broker_sessions_lock:
            session = self.broker_sessions.get(chosen_broker)
            if session is None:
                session = requests.Session()
                self.broker_sessions[chosen_broker] = session

        outcome = 'unknown'
        order_id = None
        status_message = None
        response_body = None
        sent_at = time.perf_counter()
        try:
            response = session.post(
                request_url,
                data=request_data,
                json=request_json,
                headers=request_headers,
                timeout=(3.05, 10),
                verify=verify_certificate,
            )
        except requests.exceptions.ConnectTimeout as error:
            response = None
            outcome = 'rejected'
            status_message = (
                f'could not connect to the broker, so nothing was sent: {error}'
            )
        except requests.exceptions.RequestException as error:
            response = None
            outcome = 'unknown'
            status_message = f'{type(error).__name__}: {error}'
        answered_at = time.perf_counter()

        if response is not None:
            try:
                response_body = response.json()
            except ValueError:
                response_body = response.text[:300]
            response_fields = {}
            if isinstance(response_body, dict):
                response_fields = response_body

            if response.status_code >= 300:
                error_code_keys = [
                    'error_type',
                    'errorType',
                    'errorCode',
                    'code',
                    'stat',
                ]
                error_message_keys = [
                    'message',
                    'errorMessage',
                    'emsg',
                    'description',
                    'errMsg',
                ]
                error_code = ''
                for key in error_code_keys:
                    if response_fields.get(key):
                        error_code = str(response_fields.get(key))
                        break
                nested_error = response_fields.get('error')
                if isinstance(nested_error, dict) and not error_code:
                    error_code = str(nested_error.get('code') or '')
                error_message = None
                for key in error_message_keys:
                    if response_fields.get(key):
                        error_message = str(response_fields.get(key))
                        break
                if isinstance(nested_error, dict) and not error_message:
                    error_message = nested_error.get('message')
                status_message = str(error_message or response_body)[:300]

                zerodha_rejections = [
                    'InputException',
                    'OrderException',
                    'MarginException',
                    'HoldingException',
                    'PermissionException',
                    'TokenException',
                ]
                dhan_rejection_markers = [
                    'input',
                    'order',
                    'rate_limit',
                    'rate limit',
                    'access',
                ]
                indmoney_rejection_markers = [
                    'validation',
                    'order',
                    'insufficient',
                    'invalid',
                    'margin',
                ]
                groww_rejections = [
                    'GA001',
                    'GA004',
                    'GA005',
                    'GA006',
                    'GA007',
                ]
                wisdom_capital_rejection_prefixes = (
                    'e-orders',
                    'e-order',
                    'e-rms',
                )
                lowered_code = error_code.lower()
                rejected = response.status_code < 500
                if chosen_broker == 'zerodha':
                    if error_code in zerodha_rejections:
                        rejected = True
                if chosen_broker == 'dhan':
                    for marker in dhan_rejection_markers:
                        if marker in lowered_code:
                            rejected = True
                if chosen_broker == 'indmoney':
                    for marker in indmoney_rejection_markers:
                        if marker in lowered_code:
                            rejected = True
                if chosen_broker == 'groww':
                    if error_code.upper() in groww_rejections:
                        rejected = True
                if chosen_broker == 'wisdom_capital':
                    if lowered_code.startswith(
                        wisdom_capital_rejection_prefixes,
                    ):
                        rejected = True
                if chosen_broker == 'flattrade' or chosen_broker == 'shoonya':
                    if error_code == 'Not_Ok':
                        rejected = True
                if rejected:
                    outcome = 'rejected'
                else:
                    outcome = 'unknown'

            else:
                refusal = None
                if chosen_broker == 'zerodha':
                    data = response_fields.get('data')
                    if isinstance(data, dict):
                        order_id = data.get('order_id')
                elif chosen_broker == 'dhan':
                    order_id = response_fields.get('orderId')
                elif chosen_broker == 'fyers':
                    fyers_state = response_fields.get('s')
                    if fyers_state is not None and fyers_state != 'ok':
                        refusal = response_fields.get('message')
                        if not refusal:
                            refusal = f's {fyers_state}'
                    order_id = response_fields.get('id')
                elif chosen_broker == 'groww':
                    groww_status = response_fields.get('status')
                    if groww_status is not None and groww_status != 'SUCCESS':
                        nested_error = response_fields.get('error')
                        if isinstance(nested_error, dict):
                            refusal = nested_error.get('message')
                        if not refusal:
                            refusal = response_fields.get('message')
                        if not refusal:
                            refusal = f'status {groww_status}'
                    payload = response_fields.get('payload')
                    if isinstance(payload, dict):
                        order_id = payload.get('groww_order_id')
                elif chosen_broker == 'indmoney':
                    status_text = str(response_fields.get('status', 'success'))
                    if status_text.lower() != 'success':
                        refusal = response_fields.get('message')
                        if not refusal:
                            refusal = f'status {status_text}'
                    data = response_fields.get('data')
                    if isinstance(data, dict):
                        order_id = data.get('order_id')
                elif chosen_broker == 'kotak':
                    kotak_refused = response_fields.get('stat') == 'Not_Ok'
                    if kotak_refused or response_fields.get('errMsg'):
                        refusal = response_fields.get('errMsg')
                        if not refusal:
                            refusal = 'the broker refused the request'
                    order_id = response_fields.get('nOrdNo')
                elif chosen_broker == 'stoxkart':
                    data = response_fields.get('data', response_fields)
                    if isinstance(data, dict):
                        order_id = data.get('order_id')
                elif chosen_broker == 'wisdom_capital':
                    xts_type = response_fields.get('type')
                    if xts_type is not None and xts_type != 'success':
                        refusal = response_fields.get('description')
                        if not refusal:
                            refusal = response_fields.get('message')
                        if not refusal:
                            refusal = f'type {xts_type}'
                    result = response_fields.get('result')
                    if isinstance(result, dict):
                        order_id = result.get('AppOrderID')
                else:
                    stat = str(response_fields.get('stat', ''))
                    if stat.lower() != 'ok':
                        refusal = response_fields.get('emsg')
                        if not refusal:
                            refusal = 'the broker refused the request'
                    order_id = response_fields.get('norenordno')
                    if not order_id:
                        order_id = response_fields.get('result')

                if order_id == 0 or order_id == '' or order_id == '0':
                    order_id = None
                if order_id is not None:
                    order_id = str(order_id)

                if refusal is not None:
                    outcome = 'rejected'
                    status_message = str(refusal)[:300]
                elif order_id is not None:
                    outcome = 'accepted'
                else:
                    outcome = 'unknown'
                    status_message = (
                        f'the broker answered without an order id: {str(response_body)[:300]}'
                    )

        outcome_statuses = {
            'accepted': 200,
            'rejected': 422,
            'unknown': 504,
        }
        preparation_milliseconds = (sent_at - started_at) * 1000
        broker_milliseconds = (answered_at - sent_at) * 1000
        return jsonify({
            'broker': chosen_broker,
            'instrument_id': instrument_id,
            'tag': broker_tag,
            'outcome': outcome,
            'order_id': order_id,
            'status_message': status_message,
            'broker_response': response_body,
            'skipped': skipped,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
                'broker': round(broker_milliseconds, 3),
            },
        }), outcome_statuses[outcome]

    def cancel(self):
        """Cancels one order at the broker whose order book holds it.

        The order is named by `order_id`, the broker's own order id as `POST /place` and `GET /details` answer it, given in the JSON body or the query string.
        `broker` may also be given, and is needed only when two brokers hold an order with the same id.
        With `dry_run` it answers with the request it would have sent instead of sending it.

        The broker is found by looking the order id up in every broker's `<broker>:orders:orders` hash, which the broker's order poller and order update websocket keep in Redis.
        An order can therefore be cancelled only once one of those scripts has recorded it; a Stoxkart order is recorded by its order websocket or by its once-a-second poller.
        The method reads Redis in one round trip and then sends one request to one broker.
        It never reads MongoDB or PostgreSQL and never retries a sent cancel.
        Every failure is answered with an HTTP status rather than raised.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int), which is 200 when the broker accepted the cancel or for a dry run, 422 when the broker refused it, 504 when the outcome is unknown, 400 for a malformed order_id, broker or dry_run, 401 for a missing, wrong or expired access token, 404 when no broker's order book in Redis holds the order, 409 when the order has already finished or two brokers hold the order id, and 503 when Redis cannot be read or does not hold the broker's login, settings or the order's details.
        """
        started_at = time.perf_counter()

        access_token = request.headers.get('access-token')
        if not access_token:
            return jsonify({'error': 'Access token is required'}), 401

        broker_names = [
            'dhan',
            'flattrade',
            'fyers',
            'groww',
            'indmoney',
            'kotak',
            'shoonya',
            'stoxkart',
            'wisdom_capital',
            'zerodha',
        ]

        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            message = 'the request body must be a JSON object'
            return jsonify({'error': message}), 400

        order_id = body.get('order_id')
        if order_id is None:
            order_id = request.args.get('order_id')
        if order_id is None or order_id == '':
            return jsonify({'error': 'order_id is required'}), 400
        if isinstance(order_id, int) and not isinstance(order_id, bool):
            order_id = str(order_id)
        if isinstance(order_id, str):
            order_id = order_id.strip()
        if not isinstance(order_id, str) or not re.fullmatch(
            r'[A-Za-z0-9_-]{1,64}',
            order_id,
        ):
            message = (
                'order_id must be 1 to 64 letters, digits, hyphens or underscores'
            )
            return jsonify({'error': message}), 400

        requested_broker = body.get('broker')
        if requested_broker is None:
            requested_broker = request.args.get('broker')
        if requested_broker is None or requested_broker == '':
            requested_broker = None
        else:
            requested_broker = str(requested_broker).strip().lower()
            if requested_broker not in broker_names:
                message = 'broker must be one of ' + ', '.join(broker_names)
                return jsonify({'error': message}), 400

        true_spellings = [
            'true',
            '1',
            'yes',
        ]
        false_spellings = [
            'false',
            '0',
            'no',
            '',
        ]
        raw_dry_run = body.get('dry_run')
        if raw_dry_run is None:
            raw_dry_run = request.args.get('dry_run')
        if raw_dry_run is None:
            dry_run = False
        elif isinstance(raw_dry_run, bool):
            dry_run = raw_dry_run
        elif str(raw_dry_run).strip().lower() in true_spellings:
            dry_run = True
        elif str(raw_dry_run).strip().lower() in false_spellings:
            dry_run = False
        else:
            message = 'dry_run must be true or false'
            return jsonify({'error': message}), 400

        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.hget('last_login', 'unified_broker_interface')
            pipeline.hmget('last_login', broker_names)
            pipeline.hmget('settings', broker_names)
            for broker_name in broker_names:
                pipeline.hget(f'{broker_name}:orders:orders', order_id)
            replies = pipeline.execute()
        except redis.RedisError as error:
            return jsonify({'error': f'Redis could not be read: {error}'}), 503
        token_document_text = replies[0]
        login_texts = replies[1]
        settings_texts = replies[2]
        order_texts = replies[3:]

        token_document = None
        if token_document_text:
            try:
                token_document = json.loads(token_document_text)
            except ValueError:
                token_document = None
        stored_token = None
        if isinstance(token_document, dict):
            stored_token = token_document.get('access_token')
        if not stored_token or not hmac.compare_digest(
            access_token.encode(),
            str(stored_token).encode(),
        ):
            return jsonify({'error': 'Invalid access token'}), 401
        try:
            expires_at = datetime.datetime.strptime(
                token_document['expires_at'],
                '%Y-%m-%d %H:%M:%S.%f',
            )
        except (KeyError, TypeError, ValueError):
            expires_at = None
        if expires_at is None or expires_at <= datetime.datetime.now():
            return jsonify({'error': 'Access token has expired'}), 401

        matched_entries = {}
        for position, broker_name in enumerate(broker_names):
            if requested_broker is not None and broker_name != requested_broker:
                continue
            order_text = order_texts[position]
            if not order_text:
                continue
            try:
                entry = json.loads(order_text)
            except ValueError:
                entry = None
            if isinstance(entry, dict):
                matched_entries[broker_name] = entry

        if not matched_entries:
            message = 'no broker order book in Redis holds this order_id'
            return jsonify({
                'error': message,
                'order_id': order_id,
            }), 404
        if len(matched_entries) > 1:
            message = (
                'more than one broker holds an order with this order_id, so give broker'
            )
            return jsonify({
                'error': message,
                'order_id': order_id,
                'brokers': list(matched_entries),
            }), 409

        chosen_broker = list(matched_entries)[0]
        entry = matched_entries[chosen_broker]
        order = entry.get('order')
        if not isinstance(order, dict):
            order = {}
        order_data = entry.get('data')
        if not isinstance(order_data, dict):
            order_data = {}

        order_status = order.get('status')
        finished_statuses = [
            'COMPLETE',
            'CANCELLED',
            'REJECTED',
            'EXPIRED',
        ]
        if order_status in finished_statuses:
            message = f'the order is already {order_status}'
            return jsonify({
                'error': message,
                'broker': chosen_broker,
                'order_id': order_id,
            }), 409

        settings_fields = {
            'dhan': [],
            'flattrade': [
                'username',
            ],
            'fyers': [
                'app_id',
            ],
            'groww': [],
            'indmoney': [],
            'kotak': [],
            'shoonya': [
                'ucc_code',
            ],
            'stoxkart': [
                'ucc_code',
                'api_key',
            ],
            'wisdom_capital': [
                'ucc_code',
            ],
            'zerodha': [
                'api_key',
            ],
        }

        position = broker_names.index(chosen_broker)
        login = None
        if login_texts[position]:
            try:
                login = json.loads(login_texts[position])
            except ValueError:
                login = None
        if not isinstance(login, dict) or not login.get('access_token'):
            message = f'{chosen_broker} has no login in Redis'
            return jsonify({
                'error': message,
                'broker': chosen_broker,
                'order_id': order_id,
            }), 503
        if chosen_broker == 'kotak' and not login.get('sid'):
            message = 'kotak has no sid in its login in Redis'
            return jsonify({
                'error': message,
                'broker': chosen_broker,
                'order_id': order_id,
            }), 503

        broker_settings = {}
        if settings_texts[position]:
            try:
                broker_settings = json.loads(settings_texts[position])
            except ValueError:
                broker_settings = {}
        if not isinstance(broker_settings, dict):
            broker_settings = {}
        missing_settings = []
        for settings_field in settings_fields[chosen_broker]:
            if not broker_settings.get(settings_field):
                missing_settings.append(settings_field)
        if missing_settings:
            message = (
                f'{chosen_broker} has no '
                + ', '.join(missing_settings)
                + ' in its Redis settings'
            )
            return jsonify({
                'error': message,
                'broker': chosen_broker,
                'order_id': order_id,
            }), 503

        login_token = str(login.get('access_token'))
        request_method = 'POST'
        request_url = None
        request_headers = {}
        request_params = None
        request_data = None
        request_json = None
        shown_form = None
        verify_certificate = True

        if chosen_broker == 'zerodha':
            variety = str(order_data.get('variety') or 'regular')
            request_method = 'DELETE'
            request_url = f'https://api.kite.trade/orders/{variety}/{order_id}'
            request_headers = {
                'X-Kite-Version': '3',
                'Authorization': (
                    f'token {broker_settings["api_key"]}:{login_token}'
                ),
            }

        elif chosen_broker == 'dhan':
            request_method = 'DELETE'
            request_url = f'https://api.dhan.co/v2/orders/{order_id}'
            request_headers = {
                'access-token': login_token,
            }

        elif chosen_broker == 'fyers':
            request_method = 'DELETE'
            request_url = 'https://api-t1.fyers.in/api/v3/orders/sync'
            request_headers = {
                'Authorization': f'{broker_settings["app_id"]}:{login_token}',
            }
            request_json = {
                'id': order_id,
            }

        elif chosen_broker == 'groww':
            segment = order_data.get('segment')
            if not segment:
                message = (
                    "Redis does not hold this Groww order's segment yet, so try again after Groww's next order book poll"
                )
                return jsonify({
                    'error': message,
                    'broker': chosen_broker,
                    'order_id': order_id,
                }), 503
            request_url = 'https://api.groww.in/v1/order/cancel'
            request_headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {login_token}',
                'X-API-Version': '1.0',
            }
            request_json = {
                'groww_order_id': order_id,
                'segment': str(segment),
            }

        elif chosen_broker == 'indmoney':
            segment = order_data.get('segment')
            if not segment:
                if order_id.upper().startswith('DRV'):
                    segment = 'DERIVATIVE'
                else:
                    segment = 'EQUITY'
            request_url = 'https://api.indstocks.com/order/cancel'
            request_headers = {
                'Authorization': login_token,
            }
            request_json = {
                'order_id': order_id,
                'segment': str(segment),
            }

        elif chosen_broker == 'kotak':
            base_url = str(login.get('base_url') or '').strip()
            base_url = base_url.rstrip('/')
            if not base_url or base_url == 'None':
                base_url = 'https://gw-napi.kotaksecurities.com'
            elif not base_url.startswith((
                'http://',
                'https://',
            )):
                base_url = f'https://{base_url}'
            request_url = f'{base_url}/quick/order/cancel'
            request_headers = {
                'neo-fin-key': 'neotradeapi',
                'Auth': login_token,
                'Sid': str(login.get('sid')),
            }
            kotak_fields = {
                'on': order_id,
                'am': 'NO',
            }
            request_data = {
                'jData': json.dumps(kotak_fields),
            }
            shown_form = request_data

        elif chosen_broker == 'stoxkart':
            variety = str(order_data.get('variety') or 'normal').lower()
            request_method = 'DELETE'
            request_url = (
                f'https://openapi.stoxkart.com/orders/{variety}/{order_id}'
            )
            request_headers = {
                'X-Client-Id': str(broker_settings['ucc_code']),
                'X-Platform': 'api',
                'X-Api-Key': str(broker_settings['api_key']),
                'X-Access-Token': login_token,
            }

        elif chosen_broker == 'wisdom_capital':
            if order_id.isdigit():
                application_order_id = int(order_id)
            else:
                application_order_id = order_id
            unique_identifier = order_data.get('OrderUniqueIdentifier')
            if not unique_identifier:
                unique_identifier = 'ubi'
            request_method = 'DELETE'
            request_url = 'https://trade.wisdomcapital.in/interactive/orders'
            request_headers = {
                'authorization': login_token,
            }
            request_params = {
                'appOrderID': application_order_id,
                'orderUniqueIdentifier': str(unique_identifier),
                'clientID': str(broker_settings['ucc_code']),
            }
            verify_certificate = False

        else:
            if chosen_broker == 'flattrade':
                base_url = 'https://piconnect.flattrade.in/PiConnectAPI'
                account_identifier = str(broker_settings['username'])
            else:
                base_url = 'https://api.shoonya.com/NorenWClientAPI'
                account_identifier = str(broker_settings['ucc_code'])
            request_url = f'{base_url}/CancelOrder'
            noren_fields = {
                'uid': account_identifier,
                'norenordno': order_id,
            }
            escaped_fields = json.dumps(noren_fields).replace('&', '\\u0026')
            request_data = f'jData={escaped_fields}&jKey={login_token}'
            shown_form = noren_fields

        if dry_run:
            shown_request = {
                'method': request_method,
                'url': request_url,
            }
            if request_params is not None:
                shown_request['params'] = request_params
            if shown_form is not None:
                shown_request['form'] = shown_form
            elif request_json is not None:
                shown_request['json'] = request_json
            preparation_milliseconds = (time.perf_counter() - started_at) * 1000
            return jsonify({
                'broker': chosen_broker,
                'order_id': order_id,
                'status_before_cancel': order_status,
                'dry_run': True,
                'request': shown_request,
                'timing_ms': {
                    'preparation': round(preparation_milliseconds, 3),
                },
            }), 200

        with self.broker_sessions_lock:
            session = self.broker_sessions.get(chosen_broker)
            if session is None:
                session = requests.Session()
                self.broker_sessions[chosen_broker] = session

        outcome = 'unknown'
        status_message = None
        response_body = None
        sent_at = time.perf_counter()
        try:
            response = session.request(
                request_method,
                request_url,
                params=request_params,
                data=request_data,
                json=request_json,
                headers=request_headers,
                timeout=(3.05, 10),
                verify=verify_certificate,
            )
        except requests.exceptions.ConnectTimeout as error:
            response = None
            outcome = 'rejected'
            status_message = (
                f'could not connect to the broker, so nothing was sent: {error}'
            )
        except requests.exceptions.RequestException as error:
            response = None
            outcome = 'unknown'
            status_message = f'{type(error).__name__}: {error}'
        answered_at = time.perf_counter()

        if response is not None:
            try:
                response_body = response.json()
            except ValueError:
                response_body = response.text[:300]
            response_fields = {}
            if isinstance(response_body, dict):
                response_fields = response_body

            if response.status_code >= 300:
                error_message_keys = [
                    'message',
                    'errorMessage',
                    'emsg',
                    'description',
                    'errMsg',
                ]
                error_message = None
                for key in error_message_keys:
                    if response_fields.get(key):
                        error_message = str(response_fields.get(key))
                        break
                nested_error = response_fields.get('error')
                if isinstance(nested_error, dict) and not error_message:
                    error_message = nested_error.get('message')
                status_message = str(error_message or response_body)[:300]
                if response.status_code < 500:
                    outcome = 'rejected'
                else:
                    outcome = 'unknown'

            else:
                refusal = None
                if chosen_broker == 'fyers':
                    fyers_state = response_fields.get('s')
                    if fyers_state is not None and fyers_state != 'ok':
                        refusal = response_fields.get('message')
                        if not refusal:
                            refusal = f's {fyers_state}'
                elif chosen_broker == 'groww':
                    groww_status = response_fields.get('status')
                    if groww_status is not None and groww_status != 'SUCCESS':
                        nested_error = response_fields.get('error')
                        if isinstance(nested_error, dict):
                            refusal = nested_error.get('message')
                        if not refusal:
                            refusal = response_fields.get('message')
                        if not refusal:
                            refusal = f'status {groww_status}'
                elif chosen_broker == 'indmoney':
                    status_text = str(response_fields.get('status', 'success'))
                    if status_text.lower() != 'success':
                        refusal = response_fields.get('message')
                        if not refusal:
                            refusal = f'status {status_text}'
                elif chosen_broker == 'kotak':
                    kotak_refused = response_fields.get('stat') == 'Not_Ok'
                    if kotak_refused or response_fields.get('errMsg'):
                        refusal = response_fields.get('errMsg')
                        if not refusal:
                            refusal = 'the broker refused the request'
                elif chosen_broker == 'wisdom_capital':
                    xts_type = response_fields.get('type')
                    if xts_type is not None and xts_type != 'success':
                        refusal = response_fields.get('description')
                        if not refusal:
                            refusal = response_fields.get('message')
                        if not refusal:
                            refusal = f'type {xts_type}'
                elif chosen_broker == 'flattrade' or chosen_broker == 'shoonya':
                    stat = str(response_fields.get('stat', ''))
                    if stat.lower() != 'ok':
                        refusal = response_fields.get('emsg')
                        if not refusal:
                            refusal = 'the broker refused the request'

                if refusal is not None:
                    outcome = 'rejected'
                    status_message = str(refusal)[:300]
                else:
                    outcome = 'accepted'

        outcome_statuses = {
            'accepted': 200,
            'rejected': 422,
            'unknown': 504,
        }
        preparation_milliseconds = (sent_at - started_at) * 1000
        broker_milliseconds = (answered_at - sent_at) * 1000
        return jsonify({
            'broker': chosen_broker,
            'order_id': order_id,
            'status_before_cancel': order_status,
            'outcome': outcome,
            'status_message': status_message,
            'broker_response': response_body,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
                'broker': round(broker_milliseconds, 3),
            },
        }), outcome_statuses[outcome]


orders_bp = OrdersBlueprint().blueprint
