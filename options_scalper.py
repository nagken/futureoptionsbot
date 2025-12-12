#!/usr/bin/env python3
"""
Options Scalper - Fast Calls/Puts Trading
Scalps MES/MNQ options with smart trailing stops and quick profit taking
"""
import os
import time
import yaml
from datetime import datetime
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
from threading import Thread
import logging
from collections import deque

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scalper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class OptionsScalper(EWrapper, EClient):
    def __init__(self, config):
        EClient.__init__(self, self)
        self.config = config
        self.nextOrderId = None
        self.connected = False
        
        # Market data
        self.current_price = 0
        self.bid = 0
        self.ask = 0
        self.last_price = 0
        self.price_history = deque(maxlen=100)
        
        # Futures contract tracking
        self.futures_conIds = {}  # Store qualified futures contract IDs
        self.contract_details_received = {}  # Track which contract details we've received
        
        # Options data
        self.option_chains = {}  # Store available strikes per symbol
        self.option_prices = {}
        self.chain_data_ready = {}  # Track which symbols have chain data
        self.next_req_id = 1000  # Start req IDs for option chains
        
        # Position tracking
        self.positions = {}
        self.active_orders = {}
        self.filled_orders = {}
        
        # Performance
        self.trades_today = 0
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0
        self.daily_pnl = 0
        
        # Scalping state
        self.current_signal = None
        self.entry_price = 0
        self.stop_loss_price = 0
        self.trailing_stop_price = 0
        self.highest_price_in_trade = 0
        self.lowest_price_in_trade = 999999
        
    def nextValidId(self, orderId):
        self.nextOrderId = orderId
        self.connected = True
        logger.info(f"[OK] Connected! Order ID: {orderId}")
        
    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        if errorCode not in [2104, 2106, 2158, 2107, 2119]:
            logger.error(f"Error {errorCode}: {errorString}")
    
    def contractDetails(self, reqId, contractDetails):
        """Receive contract details for futures contracts"""
        if reqId < 100:  # Futures contract detail requests (reqIds 1-99)
            contract = contractDetails.contract
            symbol = contract.symbol
            self.futures_conIds[symbol] = contract.conId
            logger.info(f"[CONTRACT] {symbol} conId={contract.conId}")
    
    def contractDetailsEnd(self, reqId):
        """Contract details complete"""
        if reqId < 100:
            self.contract_details_received[reqId] = True
    
    def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes):
        """Receive option chain data from IB"""
        if reqId >= 1000:  # Our option chain requests
            symbol_idx = reqId - 1000
            symbols = self.config.get('symbols', ['MES'])
            if symbol_idx < len(symbols):
                symbol = symbols[symbol_idx]
                logger.info(f"[CHAIN] {symbol} on {exchange}: multiplier={multiplier}, tradingClass={tradingClass}")
                logger.info(f"[CHAIN] {symbol}: {len(strikes)} strikes, {len(expirations)} expiries")
                logger.info(f"[CHAIN] {symbol} expiries: {sorted(expirations)[:5]}...")  # Show first 5
                
                # Store available strikes and expirations
                if symbol not in self.option_chains:
                    self.option_chains[symbol] = {}
                
                for expiry in expirations:
                    if expiry not in self.option_chains[symbol]:
                        self.option_chains[symbol][expiry] = []
                    self.option_chains[symbol][expiry] = sorted(strikes)
                
                self.chain_data_ready[symbol] = True
                logger.info(f"[OK] Option chain loaded for {symbol}")
    
    def securityDefinitionOptionParameterEnd(self, reqId):
        """Option chain data complete"""
        pass
            
    def tickPrice(self, reqId, tickType, price, attrib):
        """Real-time price updates"""
        if price <= 0:
            return
            
        if tickType == 1:  # Bid
            self.bid = price
            if self.current_price == 0:
                self.current_price = price
        elif tickType == 2:  # Ask
            self.ask = price
            if self.current_price == 0:
                self.current_price = price
        elif tickType == 4:  # Last
            self.last_price = price
            self.current_price = price
            self.price_history.append({
                'time': datetime.now(),
                'price': price
            })
        elif tickType == 9:  # Close price
            if self.current_price == 0:
                self.current_price = price
        
        # Build price history from bid/ask if Last price not available (off-hours)
        if len(self.price_history) < 5 and self.bid > 0 and self.ask > 0:
            mid_price = (self.bid + self.ask) / 2
            # Avoid duplicates - only add if no recent entry
            if not self.price_history or (datetime.now() - self.price_history[-1]['time']).total_seconds() > 1:
                self.price_history.append({'time': datetime.now(), 'price': mid_price})
                if self.current_price == 0:
                    self.current_price = mid_price
            
    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol, 
                             delta, optPrice, pvDividend, gamma, vega, theta, undPrice):
        """Option Greeks and pricing"""
        if reqId in self.option_prices:
            self.option_prices[reqId].update({
                'implied_vol': impliedVol,
                'delta': delta,
                'gamma': gamma,
                'theta': theta,
                'option_price': optPrice
            })
            
    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice,
                    permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        """Track order execution"""
        logger.info(f"Order {orderId}: {status} | Filled: {filled} @ ${avgFillPrice:.2f}")
        
        if orderId in self.active_orders:
            self.active_orders[orderId]['status'] = status
            self.active_orders[orderId]['filled'] = filled
            self.active_orders[orderId]['avgPrice'] = avgFillPrice
            
            if status == "Filled":
                self.filled_orders[orderId] = self.active_orders[orderId]
                del self.active_orders[orderId]
                self.on_order_filled(orderId, avgFillPrice)
                
    def position(self, account, contract, position, avgCost):
        """Track positions"""
        key = f"{contract.symbol}_{contract.strike}_{contract.right}"
        self.positions[key] = {
            'contract': contract,
            'position': position,
            'avgCost': avgCost,
            'current_value': 0
        }
        
    def on_order_filled(self, orderId, avgPrice):
        """Handle filled orders"""
        order_info = self.filled_orders.get(orderId)
        if not order_info:
            return
            
        action = order_info['action']
        if action == "BUY":
            self.entry_price = avgPrice
            self.highest_price_in_trade = avgPrice
            self.lowest_price_in_trade = avgPrice
            logger.info(f"[OK] ENTERED at ${avgPrice:.2f}")
        elif action == "SELL":
            if self.entry_price > 0:
                pnl = (avgPrice - self.entry_price) * order_info['quantity'] * 5
                self.total_pnl += pnl
                self.daily_pnl += pnl
                self.trades_today += 1
                
                if pnl > 0:
                    self.wins += 1
                    logger.info(f"[WIN] ${pnl:.2f} | Exit: ${avgPrice:.2f}")
                else:
                    self.losses += 1
                    logger.info(f"[LOSS] ${pnl:.2f} | Exit: ${avgPrice:.2f}")
                
                self.entry_price = 0


def create_option_contract(symbol, expiry, strike, right, multiplier="50"):
    """Create futures option contract - MES/MNQ options use multiplier 50
    
    For FOP contracts, use YYYYMM format for expiry (same as underlying futures)
    Example: "202603" for March 2026
    """
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "FOP"
    contract.exchange = "CME"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = expiry  # Use YYYYMM format like "202603"
    contract.strike = strike
    contract.right = right
    contract.multiplier = multiplier
    return contract


def create_futures_contract(symbol="MES", expiry="202512"):
    """Create futures contract"""
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "FUT"
    contract.exchange = "CME"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = expiry
    return contract


def connect_bot(bot, port=7496, client_id=25):
    """Connect to IBKR"""
    ports = [port, 7497, 4001, 4002]
    
    for p in ports:
        try:
            logger.info(f"Connecting to port {p}...")
            bot.connect("127.0.0.1", p, client_id)
            api_thread = Thread(target=bot.run, daemon=True)
            api_thread.start()
            time.sleep(2)
            
            if bot.isConnected():
                logger.info(f"[OK] Connected on port {p}")
                return True
        except Exception as e:
            logger.warning(f"Port {p} failed: {e}")
    
    return False


def detect_momentum(price_history, period=20):
    """
    Detect momentum direction AND reversals using recent price action
    Returns: 'BULLISH', 'BEARISH', 'REVERSAL_UP', 'REVERSAL_DOWN', or 'NEUTRAL'
    """
    if len(price_history) < period:
        return 'NEUTRAL'
    
    recent = list(price_history)[-period:]
    prices = [p['price'] for p in recent]
    
    # Calculate rate of change
    roc = (prices[-1] - prices[0]) / prices[0] * 100
    
    # Calculate momentum score
    up_moves = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
    momentum_score = up_moves / (len(prices) - 1)
    
    # Calculate recent momentum (last 5 bars for reversal detection)
    if len(prices) >= 10:
        recent_5 = prices[-5:]
        older_5 = prices[-10:-5]
        recent_roc = (recent_5[-1] - recent_5[0]) / recent_5[0] * 100
        older_roc = (older_5[-1] - older_5[0]) / older_5[0] * 100
        
        # Detect REVERSALS - when trend switches gears
        if older_roc < -0.1 and recent_roc > 0.2:  # Was falling, now rising
            return 'REVERSAL_UP'
        elif older_roc > 0.1 and recent_roc < -0.2:  # Was rising, now falling
            return 'REVERSAL_DOWN'
    
    # Detect TREND CONTINUATION
    if roc > 0.15 and momentum_score > 0.55:
        return 'BULLISH'
    elif roc < -0.15 and momentum_score < 0.45:
        return 'BEARISH'
    else:
        return 'NEUTRAL'


def find_scalping_strike(bot, symbol, expiry, current_price, direction):
    """
    Find optimal strike for scalping from REAL available options
    Use ATM or slightly ITM options for high delta/responsiveness
    
    Args:
        bot: OptionsScalper instance with chain data
        symbol: Symbol to trade (MES/MNQ)
        expiry: Target expiration date
        current_price: Current futures price
        direction: 'CALL' or 'PUT'
    """
    # Check if we have chain data
    if symbol not in bot.option_chains or expiry not in bot.option_chains[symbol]:
        logger.warning(f"[WARN] No option chain data for {symbol} {expiry}")
        # Fallback: estimate based on standard intervals
        interval = 5 if symbol == 'MES' else 50
        atm = round(current_price / interval) * interval
        return atm if direction == 'CALL' else atm
    
    # Get available strikes for this expiry
    available_strikes = bot.option_chains[symbol][expiry]
    
    if not available_strikes:
        logger.error(f"[ERROR] No strikes available for {symbol} {expiry}")
        return None
    
    # Find ATM strike from available options
    atm_strike = min(available_strikes, key=lambda x: abs(x - current_price))
    
    logger.info(f"[STRIKE] Price: ${current_price:.2f} | ATM: ${atm_strike} | Available: {len(available_strikes)} strikes")
    
    if direction == 'CALL':
        # Get slightly ITM or ATM for better delta
        itm_strikes = [s for s in available_strikes if s <= current_price]
        if itm_strikes:
            return max(itm_strikes)  # Highest strike below current price
        return atm_strike
    else:  # PUT
        # Get slightly ITM or ATM
        itm_strikes = [s for s in available_strikes if s >= current_price]
        if itm_strikes:
            return min(itm_strikes)  # Lowest strike above current price
        return atm_strike


def calculate_stops(entry_price, direction, atr, config):
    """
    Calculate tight stop loss and profit target to minimize losses
    
    Args:
        entry_price: Entry price of option
        direction: 'CALL' or 'PUT'
        atr: Average True Range for volatility
        config: Bot configuration
    """
    stop_multiplier = config.get('stop_loss_multiplier', 1.0)
    target_multiplier = config.get('profit_target_multiplier', 2.0)
    
    # TIGHTER STOPS - 10% max loss to keep losses minimal
    stop_distance = entry_price * 0.10 * stop_multiplier
    # Good profit target - 25% gain
    target_distance = entry_price * 0.25 * target_multiplier
    
    stop_loss = entry_price - stop_distance
    profit_target = entry_price + target_distance
    
    return {
        'stop_loss': max(0.05, stop_loss),  # Minimum $0.05
        'profit_target': profit_target,
        'trailing_stop_activation': entry_price * 1.15  # Activate at 15% profit
    }


def update_trailing_stop(bot, current_price, entry_price, trailing_pct=0.10):
    """
    Update trailing stop as price moves in our favor
    
    Returns: New stop level or None
    """
    if current_price <= entry_price:
        return None
    
    # Update highest price
    if current_price > bot.highest_price_in_trade:
        bot.highest_price_in_trade = current_price
    
    # Calculate trailing stop from highest price
    trailing_stop = bot.highest_price_in_trade * (1 - trailing_pct)
    
    # Only update if new stop is higher than entry
    if trailing_stop > entry_price:
        return trailing_stop
    
    return None


def place_scalp_order(bot, symbol, expiry, strike, direction, quantity=1):
    """
    Place a scalping order (buy call or put)
    
    Args:
        bot: OptionsScalper instance
        symbol: Futures symbol (MES/MNQ)
        expiry: Option expiration date
        strike: Strike price
        direction: 'CALL' or 'PUT'
        quantity: Number of contracts
    """
    if strike is None:
        logger.error(f"[ERROR] Cannot place order - invalid strike")
        return
    
    logger.info(f"[ORDER] {symbol} {direction} @ ${strike} exp {expiry}")
    contract = create_option_contract(symbol, expiry, strike, direction[0])
    
    order = Order()
    order.action = "BUY"
    order.totalQuantity = quantity
    order.orderType = "MKT"
    order.tif = "DAY"
    order.eTradeOnly = False
    order.firmQuoteOnly = False
    
    orderId = bot.nextOrderId
    bot.placeOrder(orderId, contract, order)
    
    bot.active_orders[orderId] = {
        'contract': contract,
        'action': 'BUY',
        'quantity': quantity,
        'status': 'Submitted',
        'time': datetime.now()
    }
    
    bot.nextOrderId += 1
    logger.info(f"[BUY] {direction} @ {strike} | Order: {orderId}")
    
    return orderId


def close_position(bot, symbol, expiry, strike, direction, quantity=1):
    """Close the scalping position"""
    contract = create_option_contract(symbol, expiry, strike, direction[0])
    
    order = Order()
    order.action = "SELL"
    order.totalQuantity = quantity
    order.orderType = "MKT"
    order.tif = "DAY"
    order.eTradeOnly = False
    order.firmQuoteOnly = False
    
    orderId = bot.nextOrderId
    bot.placeOrder(orderId, contract, order)
    
    bot.active_orders[orderId] = {
        'contract': contract,
        'action': 'SELL',
        'quantity': quantity,
        'status': 'Submitted',
        'time': datetime.now()
    }
    
    bot.nextOrderId += 1
    logger.info(f"[SELL] {direction} @ {strike} | Order: {orderId}")
    
    return orderId


def scalping_loop(bot, symbols, expiry):
    """
    Main scalping loop
    - Detects momentum across multiple symbols
    - Enters quick trades
    - Manages stops and targets
    - Can reverse position
    """
    config = bot.config
    max_trades = config.get('max_trades_per_day', 50)
    cooldown_seconds = config.get('cooldown_seconds', 10)
    allow_reversals = config.get('allow_reversals', True)
    
    in_position = False
    current_direction = None
    current_strike = None
    entry_price = 0
    stop_loss = 0
    profit_target = 0
    last_trade_time = datetime.now()
    debug_counter = 0  # Counter for debug output
    
    logger.info("\n" + "="*70)
    logger.info("  OPTIONS SCALPER ACTIVE")
    logger.info(f"  Trading: {', '.join(symbols)}")
    logger.info("="*70)
    
    symbol_index = 0  # Track which symbol we're checking
    
    while True:
        try:
            # Check if we hit daily limit
            if bot.trades_today >= max_trades:
                logger.info("Daily trade limit reached. Waiting for next day...")
                time.sleep(60)
                continue
            
            # Check daily loss limit
            max_daily_loss = config.get('max_daily_loss_pct', 0.10) * config.get('account_balance', 10000)
            if bot.daily_pnl < -max_daily_loss:
                logger.warning(f"Daily loss limit hit: ${bot.daily_pnl:.2f}")
                time.sleep(300)
                continue
            
            # Get current price
            if bot.current_price == 0:
                time.sleep(1)
                continue
            
            # Cycle through symbols for trading opportunities
            symbol = symbols[symbol_index % len(symbols)]
            symbol_index += 1
            
            current_price = bot.current_price
            
            # Debug output every 10 seconds (using counter instead of modulo to ensure it fires)
            if debug_counter % 20 == 0:  # 20 * 0.5s = 10 seconds
                logger.info(f"[DEBUG] {symbol} | Price: {current_price:.2f} | Bid: {bot.bid:.2f} | Ask: {bot.ask:.2f} | History: {len(bot.price_history)} bars | In Position: {in_position}")
            debug_counter += 1
            
            # Detect momentum
            signal = detect_momentum(bot.price_history)
            
            # Check if in position
            if in_position:
                # Update trailing stop to lock in profits
                new_stop = update_trailing_stop(bot, current_price, entry_price, trailing_pct=0.08)
                if new_stop and new_stop > stop_loss:
                    old_stop = stop_loss
                    stop_loss = new_stop
                    logger.info(f"[TRAIL] Stop moved: ${old_stop:.2f} → ${stop_loss:.2f} (locking profit)")
                
                # Check exit conditions
                should_exit = False
                exit_reason = ""
                
                # Profit target hit - take the win!
                if current_price >= profit_target:
                    should_exit = True
                    exit_reason = "Profit target"
                
                # Stop loss hit - minimize loss
                elif current_price <= stop_loss:
                    should_exit = True
                    exit_reason = "Stop loss"
                
                # REVERSAL DETECTED - switch gears and exit to catch opposite direction
                elif allow_reversals:
                    if signal in ['REVERSAL_DOWN', 'BEARISH'] and current_direction == 'CALL':
                        should_exit = True
                        exit_reason = "Reversal DOWN detected - switching to PUT"
                    elif signal in ['REVERSAL_UP', 'BULLISH'] and current_direction == 'PUT':
                        should_exit = True
                        exit_reason = "Reversal UP detected - switching to CALL"
                
                if should_exit:
                    logger.info(f"EXIT: {exit_reason}")
                    close_position(bot, symbol, expiry, current_strike, current_direction)
                    in_position = False
                    last_trade_time = datetime.now()
                    time.sleep(2)
            
            else:
                # Not in position - look for entry
                cooldown = (datetime.now() - last_trade_time).total_seconds()
                if cooldown < cooldown_seconds:
                    time.sleep(1)
                    continue
                
                # Check for entry signal - TREND or REVERSAL
                if signal in ['BULLISH', 'REVERSAL_UP']:
                    if signal == 'REVERSAL_UP':
                        logger.info("[SIGNAL] REVERSAL UP detected - catching the switch!")
                    else:
                        logger.info("[SIGNAL] BULLISH trend continuation")
                    
                    current_strike = find_scalping_strike(bot, symbol, expiry, current_price, 'CALL')
                    if current_strike is None:
                        logger.error("[ERROR] Could not find valid CALL strike")
                        time.sleep(5)
                        continue
                    
                    current_direction = 'CALL'
                    
                    place_scalp_order(bot, symbol, expiry, current_strike, 'CALL')
                    
                    in_position = True
                    entry_price = current_price
                    stops = calculate_stops(entry_price, 'CALL', 10, config)
                    stop_loss = stops['stop_loss']
                    profit_target = stops['profit_target']
                    
                    logger.info(f"Entry: ${entry_price:.2f} | Stop: ${stop_loss:.2f} | Target: ${profit_target:.2f}")
                    
                elif signal in ['BEARISH', 'REVERSAL_DOWN']:
                    if signal == 'REVERSAL_DOWN':
                        logger.info("[SIGNAL] REVERSAL DOWN detected - catching the switch!")
                    else:
                        logger.info("[SIGNAL] BEARISH trend continuation")
                    
                    current_strike = find_scalping_strike(bot, symbol, expiry, current_price, 'PUT')
                    if current_strike is None:
                        logger.error("[ERROR] Could not find valid PUT strike")
                        time.sleep(5)
                        continue
                    
                    current_direction = 'PUT'
                    
                    place_scalp_order(bot, symbol, expiry, current_strike, 'PUT')
                    
                    in_position = True
                    entry_price = current_price
                    stops = calculate_stops(entry_price, 'PUT', 10, config)
                    stop_loss = stops['stop_loss']
                    profit_target = stops['profit_target']
                    
                    logger.info(f"Entry: ${entry_price:.2f} | Stop: ${stop_loss:.2f} | Target: ${profit_target:.2f}")
            
            # Performance stats every 60 seconds
            if int(time.time()) % 60 == 0:
                win_rate = (bot.wins / bot.trades_today * 100) if bot.trades_today > 0 else 0
                logger.info(f"\n[STATS] {bot.trades_today} trades | {bot.wins}W-{bot.losses}L | Win Rate: {win_rate:.1f}% | P&L: ${bot.daily_pnl:.2f}\n")
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            logger.info("\nStopping scalper...")
            break
        except Exception as e:
            logger.error(f"Error in scalping loop: {e}")
            time.sleep(5)


def main():
    """Main entry point"""
    # Suppress ib_insync debug logging for clean output
    import logging
    logging.getLogger('ib_insync.wrapper').setLevel(logging.ERROR)
    logging.getLogger('ib_insync.client').setLevel(logging.ERROR)
    
    print("\n" + "="*70)
    print("  OPTIONS SCALPER - SMART TRAILING STOPS")
    print("  Fast Calls/Puts Trading with Reversals")
    print("="*70 + "\n")
    
    # Load config from YAML file
    config_file = os.path.join(os.path.dirname(__file__), 'scalper_config.yaml')
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    logger.info(f"Loaded config: symbols={config.get('symbols', config.get('symbol', 'MES'))}")
    
    # Initialize bot
    bot = OptionsScalper(config)
    
    # Connect
    if not connect_bot(bot, config['port'], config['client_id']):
        logger.error("Failed to connect to IBKR")
        return
    
    time.sleep(2)
    
    # Support both old (single symbol) and new (multiple symbols) config format
    symbols = config.get('symbols', [config.get('symbol', 'MES')])
    if isinstance(symbols, str):
        symbols = [symbols]
    
    # Step 1: Request contract details to get conIds
    logger.info("Requesting contract details for futures...")
    futures_contracts = {}
    reqId = 1
    for symbol in symbols:
        futures = create_futures_contract(symbol, config.get('futures_expiry', '202512'))
        futures_contracts[symbol] = futures
        bot.reqContractDetails(reqId, futures)
        logger.info(f"Requesting details for {symbol} (reqId={reqId})")
        reqId += 1
    
    # Wait for contract details
    logger.info("Waiting for contract details...")
    time.sleep(3)
    
    # Step 2: Subscribe to market data using the contracts
    logger.info("Subscribing to market data...")
    reqId = 100
    for symbol in symbols:
        bot.reqMktData(reqId, futures_contracts[symbol], "", False, False, [])
        logger.info(f"Subscribed to {symbol} market data (reqId={reqId})")
        reqId += 1
    
    logger.info(f"Trading: {', '.join(symbols)}")
    
    # Wait for market data connections
    time.sleep(2)
    
    # Step 3: REQUEST OPTION CHAINS using the qualified conIds
    logger.info("Fetching option chains from IB...")
    req_id = 1000
    for idx, symbol in enumerate(symbols):
        # Use the qualified conId if available, otherwise 0
        conId = bot.futures_conIds.get(symbol, 0)
        if conId > 0:
            logger.info(f"Using conId={conId} for {symbol} option chain request")
        else:
            logger.warning(f"No conId for {symbol}, will try with underlyingSymbol only")
        
        bot.reqSecDefOptParams(req_id + idx, symbol, "CME", "FUT", conId)
        logger.info(f"Requesting option chain for {symbol} on CME (reqId={req_id + idx})")
    
    # Wait for option chain data
    logger.info("Waiting for option chain data...")
    timeout = 15
    while timeout > 0:
        all_ready = all(sym in bot.chain_data_ready for sym in symbols)
        if all_ready:
            logger.info("[OK] All option chains loaded!")
            break
        time.sleep(1)
        timeout -= 1
    
    if timeout == 0:
        logger.warning("[WARN] Option chain data timeout - will use estimated strikes")
    
    logger.info("Waiting for initial price data...")
    
    # Wait for price data
    timeout = 10
    while bot.current_price == 0 and timeout > 0:
        time.sleep(1)
        timeout -= 1
    
    if bot.current_price > 0:
        logger.info(f"Current price: {bot.current_price:.2f}")
    else:
        logger.warning("No price data received yet, continuing anyway...")
    
    time.sleep(2)
    
    # Start scalping (use options_expiry for FOP contracts)
    try:
        scalping_loop(bot, symbols, config.get('options_expiry', config.get('expiry', '20251213')))
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
    finally:
        bot.disconnect()
        logger.info("Scalper stopped")


if __name__ == "__main__":
    main()
