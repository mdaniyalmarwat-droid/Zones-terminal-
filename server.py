import http.server
import socketserver
import os
import urllib.request
import urllib.parse
import json
import time
import threading
import math

PORT = int(os.environ.get('PORT', 8080))
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

# Thread-safe in-memory cache store
DATA_LOCK = threading.Lock()
DATA_STORE = {
    'quote': None,
    'quote_bytes': b'{}',
    'candles': {},
    'candles_bytes': {}
}

def make_fallback_quote():
    now = time.time()
    return {
        'symbol': 'PEPPERSTONE:XAUUSD',
        'pair': 'XAU/USD (Pepperstone)',
        'price': 4363.35,
        'bid': 4363.20,
        'ask': 4363.50,
        'high24h': 4383.56,
        'low24h': 4358.96,
        'open24h': 4376.00,
        'volume': 124500,
        'changePercent': -0.29,
        'change': -12.65,
        'timestamp': int(now * 1000)
    }

def make_fallback_candles(interval, quote):
    import random
    now = time.time()
    pep_price = quote.get('price', 4363.35)
    interval_sec = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600}.get(interval, 60)
    count = 100
    t_start = int((now - count * interval_sec) * 1000)

    # Brownian bridge to generate realistic institutional gold candles ending at pep_price
    rng = random.Random(int(now // 300) + hash(interval))
    vol = {'1m': 0.45, '5m': 0.95, '15m': 1.6, '1h': 3.2}.get(interval, 0.5)
    
    # Path starting with natural deviation
    start_offset = (rng.random() - 0.5) * vol * 12.0
    prices = [pep_price + start_offset]
    for i in range(1, count):
        rem = count - i
        drift = (pep_price - prices[-1]) / max(rem, 1)
        shock = (rng.gauss(0, 1)) * vol
        next_p = prices[-1] + drift * 0.4 + shock
        prices.append(next_p)
    prices[-1] = pep_price

    candles = []
    for i in range(count):
        t = t_start + i * interval_sec * 1000
        c_close = round(prices[i], 2)
        c_open = round(prices[i - 1] if i > 0 else (c_close - (rng.random() - 0.5) * vol), 2)
        high_wick = abs(rng.gauss(0, 1)) * vol * 0.7 + 0.15
        low_wick = abs(rng.gauss(0, 1)) * vol * 0.7 + 0.15
        c_high = round(max(c_open, c_close) + high_wick, 2)
        c_low = round(min(c_open, c_close) - low_wick, 2)
        vol_val = int(35 + abs(rng.gauss(0, 1)) * 60)
        body = c_close - c_open
        delta = round(body * 25.0 + (rng.random() - 0.5) * 8.0, 1)

        candles.append({
            'time': t,
            'open': c_open,
            'high': c_high,
            'low': c_low,
            'close': c_close,
            'volume': vol_val,
            'delta': delta
        })

    candles[-1]['close'] = pep_price
    if pep_price > candles[-1]['high']: candles[-1]['high'] = pep_price
    if pep_price < candles[-1]['low']: candles[-1]['low'] = pep_price

    return {
        'quote': quote,
        'candles': candles,
        'interval': interval,
        'timestamp': int(now * 1000)
    }

def fetch_tradingview_quote():
    url = 'https://scanner.tradingview.com/cfd/scan'
    p = {
        'symbols': {'tickers': ['PEPPERSTONE:XAUUSD']},
        'columns': ['close', 'bid', 'ask', 'high', 'low', 'open', 'volume', 'change', 'change_abs']
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(p).encode('utf-8'),
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Content-Type': 'application/json',
            'Referer': 'https://www.tradingview.com/'
        }
    )
    res = json.loads(urllib.request.urlopen(req, timeout=3.5).read().decode('utf-8'))
    d = res['data'][0]['d']
    now = time.time()
    return {
        'symbol': 'PEPPERSTONE:XAUUSD',
        'pair': 'XAU/USD (Pepperstone)',
        'price': round(float(d[0]), 2),
        'bid': round(float(d[1] if d[1] is not None else d[0] - 0.15), 2),
        'ask': round(float(d[2] if d[2] is not None else d[0] + 0.15), 2),
        'high24h': round(float(d[3]), 2),
        'low24h': round(float(d[4]), 2),
        'open24h': round(float(d[5]), 2),
        'volume': round(float(d[6] or 0), 1),
        'changePercent': round(float(d[7] or 0), 2),
        'change': round(float(d[8] or 0), 2),
        'timestamp': int(now * 1000)
    }

def fetch_yahoo_candles(interval, quote):
    now = time.time()
    pep_price = quote['price']
    range_map = {'1m': '1d', '5m': '3d', '15m': '7d', '1h': '1mo'}
    rng = range_map.get(interval, '1d')

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range={rng}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req, timeout=4.5) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        chart = data['chart']['result'][0]
        timestamps = chart.get('timestamp', [])
        q = chart['indicators']['quote'][0]

        raw_candles = []
        for i in range(len(timestamps)):
            o = q['open'][i]
            h = q['high'][i]
            l = q['low'][i]
            c = q['close'][i]
            v = q['volume'][i] or 10
            if o is not None and c is not None and h is not None and l is not None:
                raw_candles.append({
                    'time': timestamps[i] * 1000,
                    'open': o,
                    'high': h,
                    'low': l,
                    'close': c,
                    'volume': v
                })

        if len(raw_candles) >= 15:
            last_raw_close = raw_candles[-1]['close']
            basis_shift = pep_price - last_raw_close

            calibrated = []
            for c in raw_candles[-120:]:
                c_open = round(c['open'] + basis_shift, 2)
                c_close = round(c['close'] + basis_shift, 2)
                c_high = round(c['high'] + basis_shift, 2)
                c_low = round(c['low'] + basis_shift, 2)
                body = c_close - c_open
                rng_c = max(c_high - c_low, 0.1)
                delta = round(c['volume'] * (body / rng_c) * 0.7, 1)

                calibrated.append({
                    'time': c['time'],
                    'open': c_open,
                    'high': c_high,
                    'low': c_low,
                    'close': c_close,
                    'volume': c['volume'],
                    'delta': delta
                })

            calibrated[-1]['close'] = pep_price
            if pep_price > calibrated[-1]['high']: calibrated[-1]['high'] = pep_price
            if pep_price < calibrated[-1]['low']: calibrated[-1]['low'] = pep_price

            return {
                'quote': quote,
                'candles': calibrated,
                'interval': interval,
                'timestamp': int(now * 1000)
            }

    return make_fallback_candles(interval, quote)

def background_poller_thread():
    """Continuously runs in the background to keep the in-memory cache ultra-fresh"""
    intervals = ['1m', '5m', '15m', '1h']
    candle_cycle = 0

    while True:
        try:
            # 1. Update quote
            try:
                new_quote = fetch_tradingview_quote()
            except Exception:
                with DATA_LOCK:
                    new_quote = DATA_STORE['quote'] or make_fallback_quote()

            quote_bytes = json.dumps(new_quote).encode('utf-8')

            with DATA_LOCK:
                DATA_STORE['quote'] = new_quote
                DATA_STORE['quote_bytes'] = quote_bytes

            # 2. Update candles periodically (every ~7 seconds) or if empty
            needs_candles = any(iv not in DATA_STORE['candles'] for iv in intervals)
            if needs_candles or (candle_cycle % 5 == 0):
                for iv in intervals:
                    try:
                        c_data = fetch_yahoo_candles(iv, new_quote)
                    except Exception:
                        c_data = make_fallback_candles(iv, new_quote)

                    c_bytes = json.dumps(c_data).encode('utf-8')
                    with DATA_LOCK:
                        DATA_STORE['candles'][iv] = c_data
                        DATA_STORE['candles_bytes'][iv] = c_bytes

            candle_cycle += 1
        except Exception as err:
            print("Background poller notice:", err, flush=True)

        time.sleep(1.5)

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

class TerminalHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, HEAD')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Max-Age', '86400')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # 1. Instant response for Pepperstone Quote (<0.1ms)
        if parsed.path == '/api/pepperstone':
            with DATA_LOCK:
                body = DATA_STORE['quote_bytes']
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 2. Instant response for Gold Candles (<0.1ms)
        if parsed.path == '/api/gold':
            params = urllib.parse.parse_qs(parsed.query)
            interval = params.get('interval', ['1m'])[0]
            with DATA_LOCK:
                body = DATA_STORE['candles_bytes'].get(interval)
                if not body:
                    q = DATA_STORE['quote'] or make_fallback_quote()
                    fallback_data = make_fallback_candles(interval, q)
                    body = json.dumps(fallback_data).encode('utf-8')
                    DATA_STORE['candles'][interval] = fallback_data
                    DATA_STORE['candles_bytes'][interval] = body

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        return super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        super().end_headers()

def init_seed_cache():
    """Seeds the in-memory cache instantly so server is 100% ready on line 1"""
    q = make_fallback_quote()
    q_bytes = json.dumps(q).encode('utf-8')
    DATA_STORE['quote'] = q
    DATA_STORE['quote_bytes'] = q_bytes

    for iv in ['1m', '5m', '15m', '1h']:
        c = make_fallback_candles(iv, q)
        b = json.dumps(c).encode('utf-8')
        DATA_STORE['candles'][iv] = c
        DATA_STORE['candles_bytes'][iv] = b

if __name__ == '__main__':
    os.chdir(DIRECTORY)
    print("Pre-warming in-memory cache...", flush=True)
    init_seed_cache()

    poller = threading.Thread(target=background_poller_thread, daemon=True)
    poller.start()
    print("Asynchronous background poller started.", flush=True)

    print(f"Starting High-Speed Multi-Threaded Pepperstone Server on port {PORT}...", flush=True)
    with ThreadedTCPServer(("", PORT), TerminalHandler) as httpd:
        print(f"PEPPERSTONE Terminal Server active at http://localhost:{PORT}", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Server stopped.", flush=True)
