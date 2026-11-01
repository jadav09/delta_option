"""Local Delta Exchange options dashboard. Credentials remain in process memory only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, urlencode
from datetime import datetime, timezone
import hashlib, hmac, ipaddress, json, os, re, secrets, time, urllib.request, urllib.error, threading

HOST, PORT = "127.0.0.1", 8765
BASES = {"India": "https://api.india.delta.exchange", "Global": "https://api.delta.exchange",
         "India Testnet": "https://cdn-ind.testnet.deltaex.org", "Global Testnet": "https://testnet-api.delta.exchange"}
SESSION = {"key": None, "secret": None, "base": None, "positions": [], "orders": [], "order_events": [], "logs": [], "signals": [], "authenticated": False, "auto_armed": False}
ORDER_LOCK = threading.Lock()
ASSETS = {"BTC": "BTCUSD", "ETH": "ETHUSD", "XAUT": "XAUTUSD"}

def add_session_activity(message, level="info"):
    row={"time":time.time(),"message":str(message)[:400],"level":level if level in {"info","error","scan","success"} else "info"}
    SESSION["logs"].insert(0,row); del SESSION["logs"][100:]
    return row

def add_order_activity(status, symbol, side, detail, order_id=None):
    row={"time":time.time(),"status":str(status)[:32],"symbol":str(symbol)[:80],"side":str(side)[:24],"detail":str(detail)[:300],"order_id":str(order_id)[:64] if order_id else ""}
    SESSION["order_events"].insert(0,row); del SESSION["order_events"][50:]
    add_session_activity(f"Order {row['status'].lower()}: {row['symbol']} {row['side']} · {row['detail']}", "error" if row["status"].lower() in {"rejected","skipped"} else "success")
    return row

def api(method, path, params=None, body=None, private=False, session_base=False):
    params = params or {}
    query = "?" + urlencode(params) if params else ""
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    headers = {"Accept": "application/json", "User-Agent": "Local-Delta-Options/1.0"}
    if payload: headers["Content-Type"] = "application/json"
    if private:
        if not SESSION["authenticated"]: raise ValueError("Authenticate with Delta before requesting this action.")
        stamp = str(int(time.time()))
        message = method.upper() + stamp + path + query + payload
        signature = hmac.new(SESSION["secret"].encode(), message.encode(), hashlib.sha256).hexdigest()
        headers.update({"api-key": SESSION["key"], "timestamp": stamp, "signature": signature})
    req = urllib.request.Request((SESSION["base"] if private or session_base else BASES.get("India")) + path + query,
          data=payload.encode() if payload else None, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=15) as response: result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        try: detail = json.loads(exc.read().decode())
        except Exception: detail = {"error": exc.reason}
        message = detail.get("error", detail.get("message", detail.get("error_code", "Delta rejected the request"))) if isinstance(detail, dict) else "Delta rejected the request"
        if isinstance(message, dict):
            code = message.get("code") or message.get("error_code")
            reason = message.get("message") or message.get("detail") or json.dumps(message, separators=(",", ":"))
            if code == "ip_not_whitelisted_for_api_key":
                context = message.get("context") or (detail.get("context", {}) if isinstance(detail, dict) else {})
                client_ip = context.get("client_ip") if isinstance(context, dict) else None
                try: client_ip = str(ipaddress.ip_address(str(client_ip))) if client_ip else None
                except ValueError: client_ip = None
                ip_note = f" Delta reports your current public IP as {client_ip}." if client_ip else " Use the client_ip value in Delta's error response."
                message = ("This computer's current public IP is not on this API key's Delta allowlist." + ip_note +
                           " In Delta API Management, add that IP to the key's whitelist, save, then connect again. "
                           "If you use a VPN or change networks, the public IP may change. This is an IP allowlist issue, not a secret-validation error.")
            else:
                message = f"{code}: {reason}" if code else reason
        elif isinstance(message, str) and "ip_not_whitelisted_for_api_key" in message:
            match = re.search(r"client_ip['\"]?\s*:\s*['\"]?([^,'\"\]}\s]+)", message)
            client_ip = match.group(1).rstrip("'") if match else None
            try: client_ip = str(ipaddress.ip_address(client_ip)) if client_ip else None
            except ValueError: client_ip = None
            ip_note = f" Delta reports your current public IP as {client_ip}." if client_ip else " Copy the complete client_ip value from Delta's response."
            message = ("This computer's current public IP is not on this API key's Delta allowlist." + ip_note +
                       " In Delta API Management, add that exact IP to the key's whitelist, save, then connect again. "
                       "If you use a VPN or change networks, the public IP may change. This is an IP allowlist issue, not a secret-validation error.")
        raise RuntimeError(f"Delta API {exc.code}: {message}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        if getattr(reason, "winerror", None) == 10013 or getattr(reason, "errno", None) in (13, 10013):
            raise RuntimeError("Windows blocked this local app from opening a connection to Delta (WinError 10013). Allow the Python executable through Windows Firewall or endpoint security, then restart this dashboard. This is a network-permission error, not an API-key rejection.") from None
        raise RuntimeError(f"Delta connection failed: {reason}") from None
    if isinstance(result, dict) and result.get("success") is False: raise RuntimeError(result.get("error", result.get("message", "Delta request failed")))
    return result.get("result", result) if isinstance(result, dict) else result

def reply(handler, data, code=200):
    raw=json.dumps(data, separators=(",", ":")).encode(); handler.send_response(code); handler.send_header("Content-Type","application/json; charset=utf-8"); handler.send_header("Cache-Control","no-store"); handler.send_header("Content-Length",str(len(raw))); handler.end_headers(); handler.wfile.write(raw)

def sync_tracked_positions():
    """Release a side lock only after Delta no longer reports its tracked option position."""
    if not SESSION["authenticated"] or not SESSION["positions"]: return
    try:
        result=api("GET","/v2/positions/margined",private=True)
        rows=result if isinstance(result,list) else result.get("positions",[]) if isinstance(result,dict) else []
        open_products={int(p.get("product_id",0)) for p in rows if int(float(p.get("size",0) or 0))!=0}
        now=time.time()
        for row in list(SESSION["positions"]):
            if int(row.get("product_id",0)) in open_products:
                row["active"]=True
            elif now-float(row.get("created_epoch",now))>=30:
                row["active"]=False
                if row in SESSION["positions"]: SESSION["positions"].remove(row)
                if row in SESSION["orders"]: SESSION["orders"].remove(row)
    except Exception:
        # Keep the lock on API errors; a failed status check must not permit a duplicate signal.
        return

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        parsed=urlparse(self.path); p=parsed.path
        if p=="/":
            try:
                with open(os.path.join(os.path.dirname(__file__),"index.html"),"rb") as f: data=f.read()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
            except Exception: reply(self,{"error":"Dashboard file is unavailable"},500)
            return
        try:
            if p=="/api/status":
                sync_tracked_positions()
                return reply(self,{"authenticated":SESSION["authenticated"],"auto_armed":SESSION["auto_armed"],"positions":SESSION["positions"],"orders":SESSION["orders"],"order_events":SESSION["order_events"],"logs":SESSION["logs"],"signals":SESSION["signals"]})
            if p=="/api/ticker":
                symbol=ASSETS.get(parse_qs(parsed.query).get("asset",["BTC"])[0]);
                if not symbol: raise ValueError("Choose BTC, ETH, or XAUT.")
                return reply(self,{"data":api("GET","/v2/tickers/"+symbol)})
            if p=="/api/options":
                asset=parse_qs(parsed.query).get("asset",["BTC"])[0]
                if asset not in ASSETS: raise ValueError("Choose BTC, ETH, or XAUT.")
                return reply(self,{"data":api("GET","/v2/tickers",{"contract_types":"call_options,put_options","underlying_asset_symbols":asset})})
            if p=="/api/candles":
                q=parse_qs(parsed.query); asset=q.get("asset",["BTC"])[0]; frame=q.get("timeframe",["5m"])[0]
                if asset not in ASSETS: raise ValueError("Unsupported asset")
                if frame not in {"1m","3m","5m","15m","30m","1h","2h","4h","6h","1d","1w"}: raise ValueError("Unsupported timeframe")
                now=int(time.time()); mins={"1m":1,"3m":3,"5m":5,"15m":15,"30m":30,"1h":60,"2h":120,"4h":240,"6h":360,"1d":1440,"1w":10080}[frame]
                return reply(self,{"data":api("GET","/v2/history/candles",{"resolution":frame,"symbol":ASSETS[asset],"start":now-mins*60*180,"end":now})})
            if p=="/api/option-candles":
                q=parse_qs(parsed.query); symbol=q.get("symbol",[""])[0]; frame=q.get("timeframe",["5m"])[0]
                if not symbol or len(symbol)>40 or not all(c.isalnum() or c in "-_" for c in symbol): raise ValueError("Invalid option symbol")
                if frame not in {"1m","3m","5m","15m","30m","1h","2h","4h","6h","1d","1w"}: raise ValueError("Unsupported timeframe")
                mins={"1m":1,"3m":3,"5m":5,"15m":15,"30m":30,"1h":60,"2h":120,"4h":240,"6h":360,"1d":1440,"1w":10080}[frame]; now=int(time.time())
                return reply(self,{"data":api("GET","/v2/history/candles",{"resolution":frame,"symbol":symbol,"start":now-mins*60*180,"end":now})})
            if p=="/api/private/positions": return reply(self,{"data":api("GET","/v2/positions/margined",private=True)})
            reply(self,{"error":"Not found"},404)
        except Exception as exc: reply(self,{"error":str(exc)},400)
    def do_POST(self):
        p=urlparse(self.path).path; data={}
        try:
            length=int(self.headers.get("Content-Length","0")); data=json.loads(self.rfile.read(length) or b"{}")
            if p=="/api/auth":
                key=str(data.get("key","")).strip(); secret=str(data.get("secret","")); env=data.get("environment","India")
                if not key or not secret: raise ValueError("Enter both your Delta API key and secret.")
                if env not in BASES: raise ValueError("Choose a valid Delta environment.")
                # Verify in temporary candidate state; discard on every failure.
                old=(SESSION["key"],SESSION["secret"],SESSION["base"],SESSION["authenticated"])
                SESSION.update(key=key,secret=secret,base=BASES[env],authenticated=True,auto_armed=False)
                try: api("GET","/v2/wallet/balances",private=True)
                except Exception: SESSION.update(key=None,secret=None,base=None,authenticated=False); raise
                SESSION["positions"].clear(); SESSION["orders"].clear(); SESSION["signals"].clear()
                return reply(self,{"ok":True,"message":f"Connected to Delta {env}. Secret held in memory until this server stops."})
            if p=="/api/logout":
                SESSION.update(key=None,secret=None,base=None,authenticated=False,auto_armed=False); return reply(self,{"ok":True})
            if p=="/api/activity":
                message=str(data.get("message","Activity"))[:400]
                level=str(data.get("level","info"))
                event=None
                order_event=None
                if data.get("category")=="order":
                    status=str(data.get("status","Skipped"))
                    if status not in {"Accepted","Rejected","Skipped","Close requested","Closed"}: raise ValueError("Unsupported order activity type.")
                    order_event=add_order_activity(status,data.get("symbol",data.get("asset","—")),data.get("side","—"),message,data.get("order_id"))
                    event=SESSION["logs"][0]
                else: event=add_session_activity(message,level)
                return reply(self,{"ok":True,"event":event,"order_event":order_event})
            if p=="/api/arm":
                with ORDER_LOCK:
                    if not SESSION["authenticated"]: raise ValueError("Connect and verify Delta before arming live auto execution.")
                    SESSION["auto_armed"]=True
                return reply(self,{"ok":True,"auto_armed":True})
            if p=="/api/disarm":
                with ORDER_LOCK: SESSION["auto_armed"]=False
                return reply(self,{"ok":True,"auto_armed":False})
            if p=="/api/order":
                with ORDER_LOCK:
                    if not SESSION["auto_armed"]: raise ValueError("Auto execution is disarmed; no order was submitted.")
                    product=int(data.get("product_id",0)); size=int(data.get("size",0)); symbol=str(data.get("symbol","")); direction=str(data.get("signal_side","")); asset=str(data.get("asset",""))
                    entry=float(data.get("entry",0)); stop=float(data.get("stop",0)); target=float(data.get("target",0))
                    expected_prefix="C" if direction=="CALL" else "P"
                    contract_match=re.fullmatch(rf"{expected_prefix}-{asset}-\d+-(\d{{2}})(\d{{2}})(\d{{2}})",symbol) if asset in ASSETS and direction in {"CALL","PUT"} else None
                    if asset not in ASSETS or direction not in {"CALL","PUT"} or product<=0 or size<=0 or not contract_match or min(entry,stop,target)<=0 or stop>=entry or target<=entry: raise ValueError("Invalid asset, contract, signal side, size, or option-based bracket prices.")
                    day,month,year=map(int,contract_match.groups())
                    expiry_at=datetime(2000+year,month,day,12,tzinfo=timezone.utc).timestamp()
                    if expiry_at-time.time()<=60*60: raise ValueError("Contract expires in less than 60 minutes; no order was sent.")
                    if any(row.get("asset")==asset and row.get("side")==direction and row.get("active",True) for row in SESSION["positions"]):
                        raise ValueError(f"A {asset} {direction} position is already tracked; duplicate entry blocked.")
                    # Require the scan's ask to still match the live ask; never chase a stale quote.
                    quote=api("GET","/v2/tickers/"+symbol,session_base=True)
                    fresh_ask=float((quote.get("quotes") or {}).get("best_ask",0)) if isinstance(quote,dict) else 0
                    tick_size=float(quote.get("tick_size",0.01) or 0.01) if isinstance(quote,dict) else 0.01
                    if fresh_ask<=0: raise ValueError("Current option best ask is unavailable; no order was sent.")
                    if abs(fresh_ask-entry)>max(tick_size,0.00000001): raise ValueError(f"Option ask changed from {entry:g} to {fresh_ask:g} before submission; no order was sent. Scanner will recheck the quote.")
                    entry=fresh_ask
                    # IOC limit buys cap the fill at the freshly verified best ask; an unavailable fill is cancelled.
                    order=api("POST","/v2/orders",body={"product_id":product,"product_symbol":symbol,"size":size,"side":"buy","order_type":"limit_order","limit_price":str(entry),"time_in_force":"ioc","bracket_stop_loss_price":str(stop),"bracket_take_profit_price":str(target),"bracket_stop_trigger_method":"last_traded_price","client_order_id":"local_"+secrets.token_hex(10)},private=True)
                    order=order if isinstance(order,dict) else {}
                    order_state=str(order.get("state","submitted")); unfilled=int(float(order.get("unfilled_size",0) or 0)); filled=max(0,size-unfilled) if "unfilled_size" in order else (0 if order_state.lower() in {"rejected","cancelled","canceled"} and not order.get("average_fill_price") else size)
                    fill_price=float(order.get("average_fill_price") or entry) if filled>0 else 0
                    if filled==0:
                        status="Rejected" if order_state.lower()=="rejected" else "Skipped"
                        add_order_activity(status,symbol,direction,f"IOC limit at {entry:g} was not filled; no position opened and no higher-price buy was sent.",order.get("id"))
                        return reply(self,{"ok":True,"order":{"id":order.get("id"),"symbol":symbol,"state":order_state,"filled":False,"limit_price":entry}})
                    row={"id":order.get("id"),"asset":asset,"product_id":product,"symbol":symbol,"side":direction,"size":filled or size,"entry":fill_price or entry,"fill_price":fill_price or None,"limit_price":entry,"filled":filled>0,"stop":stop,"target":target,"status":order_state,"time":time.strftime("%H:%M:%S"),"created_epoch":time.time(),"active":True}
                    SESSION["orders"].insert(0,row); SESSION["positions"].insert(0,row)
                    order_state=str(row.get("status","submitted")).lower()
                    event_status="Accepted" if filled>0 else ("Rejected" if order_state=="rejected" else "Skipped")
                    add_order_activity(event_status,symbol,direction,f"IOC limit {entry:g} · fill {fill_price:g} · size {row['size']} · stop {stop:g} · target {target:g}",row.get("id"))
                return reply(self,{"ok":True,"order":row})
            if p=="/api/positions/close-one":
                if not SESSION["authenticated"]: raise ValueError("Connect Delta before closing a position.")
                product_id=int(data.get("product_id",0))
                if product_id<=0: raise ValueError("Invalid product ID.")
                response=api("GET","/v2/positions/margined",{"product_ids":str(product_id)},private=True)
                rows=response if isinstance(response,list) else response.get("positions",[]) if isinstance(response,dict) else []
                position=next((row for row in rows if int(row.get("product_id",0))==product_id and int(float(row.get("size",0) or 0))!=0),None)
                if not position:
                    add_order_activity("Closed",str(data.get("symbol",product_id)),"—","Position was already closed.")
                    return reply(self,{"ok":True,"closed":True,"message":"Position is already closed."})
                size=int(abs(float(position.get("size",0) or 0)))
                if size<=0: raise ValueError("Delta returned an invalid position size.")
                result=api("POST","/v2/orders",body={"product_id":product_id,"product_symbol":position.get("product_symbol"),"size":size,"side":"sell" if float(position["size"])>0 else "buy","order_type":"market_order","reduce_only":True,"client_order_id":"exit_"+secrets.token_hex(9)},private=True)
                add_order_activity("Close requested",position.get("product_symbol",product_id),"Exit",f"Reduce-only market exit submitted · size {size}",result.get("id") if isinstance(result,dict) else None)
                return reply(self,{"ok":True,"closed":False,"order":result,"message":"Reduce-only market exit submitted."})
            if p=="/api/positions/close-all":
                if not SESSION["authenticated"]: raise ValueError("Connect Delta before closing positions.")
                with ORDER_LOCK: SESSION["auto_armed"]=False
                result=api("POST","/v2/positions/close_all",body={"close_all_portfolio":True,"close_all_isolated":True,"user_id":0},private=True)
                add_order_activity("Close requested","All positions","Exit all","Delta account-wide close request submitted.")
                return reply(self,{"ok":True,"result":result,"message":"Auto execution disarmed and Delta close-all request submitted."})
            if p=="/api/stop-close":
                with ORDER_LOCK: SESSION["auto_armed"]=False
                # Only cancel and close option products tracked by this local session.
                for order in list(SESSION["orders"]):
                    if order.get("id") and order.get("product_id") and str(order.get("status","")).lower() in {"open","pending","submitted"}:
                        api("DELETE","/v2/orders",body={"id":order["id"],"product_id":order["product_id"]},private=True)
                tracked_sizes={}
                for row in SESSION["positions"]:
                    if row.get("product_id"):
                        pid=int(row["product_id"]); tracked_sizes[pid]=tracked_sizes.get(pid,0)+int(row.get("size",0))
                product_ids=sorted(tracked_sizes)
                for product_id in product_ids:
                    positions=api("GET","/v2/positions/margined",{"product_ids":str(product_id)},private=True)
                    items=positions if isinstance(positions,list) else positions.get("positions",[]) if isinstance(positions,dict) else []
                    for pos in items:
                        size=float(pos.get("size",0) or 0)
                        close_size=min(abs(int(size)),tracked_sizes[product_id])
                        if close_size:
                            api("POST","/v2/orders",body={"product_id":product_id,"product_symbol":pos.get("product_symbol"),"size":close_size,"side":"sell" if size>0 else "buy","order_type":"market_order","reduce_only":True,"client_order_id":"close_"+secrets.token_hex(9)},private=True)
                SESSION["positions"].clear(); SESSION["orders"].clear(); SESSION["signals"].clear(); add_session_activity("Stop and close tracked positions completed; activity history retained.","success")
                return reply(self,{"ok":True,"message":"Orders cancelled, positions close requests confirmed, session cleared."})
            if p=="/api/session/clear":
                sync_tracked_positions()
                if SESSION["positions"]: raise ValueError("Tracked option positions are still open; the session lock stays active until Delta reports they are closed.")
                SESSION["positions"].clear(); SESSION["orders"].clear(); SESSION["signals"].clear(); return reply(self,{"ok":True})
            reply(self,{"error":"Not found"},404)
        except Exception as exc:
            if p=="/api/order": add_order_activity("Skipped" if "no order was sent" in str(exc) else "Rejected",data.get("symbol",data.get("asset","Order")),data.get("signal_side","—"),str(exc))
            elif p in {"/api/positions/close-one","/api/positions/close-all"}: add_order_activity("Rejected","Exit request","Exit",str(exc))
            reply(self,{"error":str(exc)},400)

if __name__=="__main__":
    print(f"Delta local dashboard: http://{HOST}:{PORT}")
    try: ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
    except KeyboardInterrupt: pass
    finally: SESSION.update(key=None,secret=None,base=None,authenticated=False,auto_armed=False)
