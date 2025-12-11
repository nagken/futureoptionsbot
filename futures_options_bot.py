#!/usr/bin/env python3
"""
Futures Options Trading Bot
Trades options on MES/MNQ futures using Iron Condor and Butterfly strategies
"""
import time
import yaml
from datetime import datetime, timedelta
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
from threading import Thread
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('options_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class OptionsBot(EWrapper, EClient):
    def __init__(self, config):
        EClient.__init__(self, self)
        self.config = config
        self.nextOrderId = None
        self.positions = {}
        self.account_value = 0
        self.daily_pnl = 0
        self.option_chains = {}
        self.active_trades = []
        self.connected = False
        
    def nextValidId(self, orderId):
        """Callback when connection is established"""
        self.nextOrderId = orderId
        self.connected = True
        logger.info(f"Connected! Next order ID: {orderId}")
        
    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        """Handle errors"""
        if errorCode not in [2104, 2106, 2158, 2107, 2119]:
            logger.error(f"Error {errorCode}: {errorString}")
            
    def position(self, account, contract, position, avgCost):
        """Track positions"""
        key = f"{contract.symbol}_{contract.strike}_{contract.right}"
        self.positions[key] = {
            'contract': contract,
            'position': position,
            'avgCost': avgCost
        }
        logger.info(f"Position: {key} | Qty: {position} | Avg: ${avgCost:.2f}")
        
    def positionEnd(self):
        """Called when all positions received"""
        logger.info(f"Total positions: {len(self.positions)}")
        
    def accountSummary(self, reqId, account, tag, value, currency):
        """Track account value"""
        if tag == "NetLiquidation":
            self.account_value = float(value)
        elif tag == "DailyPnL":
            self.daily_pnl = float(value)
            
    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, 
                    permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        """Track order status"""
        logger.info(f"Order {orderId}: {status} | Filled: {filled} @ ${avgFillPrice:.2f}")
        
    def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId, 
                                         tradingClass, multiplier, expirations, strikes):
        """Receive option chain data"""
        self.option_chains[reqId] = {
            'exchange': exchange,
            'expirations': expirations,
            'strikes': sorted(strikes)
        }
        
    def securityDefinitionOptionParameterEnd(self, reqId):
        """Option chain data complete"""
        logger.info(f"Option chain loaded for request {reqId}")


def load_config(config_file='10_config/config_options_bot.yaml'):
    """Load configuration from YAML file"""
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        logger.info(f"Configuration loaded from {config_file}")
        return config
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return None


def create_futures_contract(symbol="MES", expiry="202512"):
    """Create futures contract for options"""
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "FUT"
    contract.exchange = "CME"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = expiry
    return contract


def create_option_contract(symbol, expiry, strike, right, multiplier="5"):
    """Create option contract"""
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "FOP"  # Futures Option
    contract.exchange = "CME"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = expiry
    contract.strike = strike
    contract.right = right  # "C" or "P"
    contract.multiplier = multiplier
    return contract


def create_market_order(action, quantity):
    """Create a market order"""
    order = Order()
    order.action = action  # "BUY" or "SELL"
    order.totalQuantity = quantity
    order.orderType = "MKT"
    return order


def create_limit_order(action, quantity, price):
    """Create a limit order"""
    order = Order()
    order.action = action
    order.totalQuantity = quantity
    order.orderType = "LMT"
    order.lmtPrice = price
    return order


def connect_to_ibkr(bot, port=7496, client_id=10):
    """Connect to Interactive Brokers"""
    ports_to_try = [port, 7497, 4001, 4002]
    
    for p in ports_to_try:
        try:
            logger.info(f"Attempting connection on port {p}...")
            bot.connect("127.0.0.1", p, client_id)
            api_thread = Thread(target=bot.run, daemon=True)
            api_thread.start()
            time.sleep(2)
            
            if bot.isConnected():
                logger.info(f"✓ Connected to IBKR on port {p}")
                return True
        except Exception as e:
            logger.warning(f"Port {p} failed: {e}")
            continue
    
    logger.error("Failed to connect to IBKR on any port")
    return False


def get_option_chain(bot, symbol="MES"):
    """Request option chain for futures"""
    logger.info(f"Requesting option chain for {symbol}...")
    
    futures_contract = create_futures_contract(symbol)
    bot.reqSecDefOptParams(1, symbol, "", "FUT", futures_contract.conId)
    
    time.sleep(3)
    return bot.option_chains.get(1, None)


def calculate_iron_condor_strikes(current_price, delta_target=15, wing_width=10):
    """Calculate strikes for iron condor based on delta target"""
    # Simplified - in production, use actual Greeks
    # For 15 delta, roughly 1 standard deviation
    offset = current_price * 0.03  # ~3% away
    
    call_short = round(current_price + offset)
    call_long = call_short + wing_width
    put_short = round(current_price - offset)
    put_long = put_short - wing_width
    
    return {
        'call_short': call_short,
        'call_long': call_long,
        'put_short': put_short,
        'put_long': put_long
    }


def place_iron_condor(bot, symbol, expiry, strikes, quantity=1):
    """Place an iron condor spread"""
    logger.info(f"Placing Iron Condor on {symbol}:")
    logger.info(f"  Call spread: {strikes['call_short']}/{strikes['call_long']}")
    logger.info(f"  Put spread: {strikes['put_short']}/{strikes['put_long']}")
    
    orders = []
    
    # Sell call
    call_short = create_option_contract(symbol, expiry, strikes['call_short'], "C")
    order1 = create_market_order("SELL", quantity)
    bot.placeOrder(bot.nextOrderId, call_short, order1)
    orders.append(bot.nextOrderId)
    bot.nextOrderId += 1
    
    # Buy call (protection)
    call_long = create_option_contract(symbol, expiry, strikes['call_long'], "C")
    order2 = create_market_order("BUY", quantity)
    bot.placeOrder(bot.nextOrderId, call_long, order2)
    orders.append(bot.nextOrderId)
    bot.nextOrderId += 1
    
    # Sell put
    put_short = create_option_contract(symbol, expiry, strikes['put_short'], "P")
    order3 = create_market_order("SELL", quantity)
    bot.placeOrder(bot.nextOrderId, put_short, order3)
    orders.append(bot.nextOrderId)
    bot.nextOrderId += 1
    
    # Buy put (protection)
    put_long = create_option_contract(symbol, expiry, strikes['put_long'], "P")
    order4 = create_market_order("BUY", quantity)
    bot.placeOrder(bot.nextOrderId, put_long, order4)
    orders.append(bot.nextOrderId)
    bot.nextOrderId += 1
    
    logger.info(f"Iron Condor orders placed: {orders}")
    return orders


def monitor_positions(bot):
    """Monitor and manage open positions"""
    bot.reqPositions()
    time.sleep(2)
    
    logger.info("\n" + "="*70)
    logger.info("CURRENT POSITIONS")
    logger.info("="*70)
    
    if not bot.positions:
        logger.info("No open positions")
    else:
        for key, pos in bot.positions.items():
            logger.info(f"{key}: {pos['position']} @ ${pos['avgCost']:.2f}")
    
    logger.info(f"\nAccount Value: ${bot.account_value:,.2f}")
    logger.info(f"Daily P&L: ${bot.daily_pnl:,.2f}")
    logger.info("="*70 + "\n")


def main():
    """Main trading loop"""
    print("\n" + "="*70)
    print("  FUTURES OPTIONS TRADING BOT")
    print("  Strategy: Iron Condor on MES/MNQ")
    print("="*70 + "\n")
    
    # Load configuration
    config = load_config()
    if not config:
        logger.error("Failed to load configuration. Exiting.")
        return
    
    # Initialize bot
    bot = OptionsBot(config)
    
    # Connect to IBKR
    if not connect_to_ibkr(bot, port=config.get('port', 7496), 
                           client_id=config.get('client_id', 10)):
        return
    
    # Wait for connection to stabilize
    time.sleep(2)
    
    # Request account updates
    bot.reqAccountSummary(9001, "All", "NetLiquidation,DailyPnL")
    time.sleep(1)
    
    # Monitor positions
    monitor_positions(bot)
    
    # Check if we should enter new trades
    symbol = config.get('symbol', 'MES')
    max_positions = config.get('max_positions', 3)
    
    if len(bot.positions) < max_positions:
        logger.info(f"\nChecking for entry opportunity on {symbol}...")
        
        # Get current price (simplified - should get actual market data)
        current_price = 6000  # Placeholder - implement real price fetch
        
        # Calculate strikes
        strikes = calculate_iron_condor_strikes(
            current_price,
            delta_target=config.get('delta_target', 0.15),
            wing_width=config.get('wing_width', 10)
        )
        
        # Get expiry (next weekly)
        expiry = "20251219"  # Placeholder - calculate actual expiry
        
        # Place iron condor
        # Uncomment to trade live:
        # place_iron_condor(bot, symbol, expiry, strikes, quantity=1)
        logger.info("Trade simulation mode - no orders placed")
    
    # Keep running
    logger.info("\nBot running. Press Ctrl+C to stop...")
    try:
        while True:
            time.sleep(60)
            monitor_positions(bot)
    except KeyboardInterrupt:
        logger.info("\nShutting down bot...")
        bot.disconnect()
        logger.info("Bot stopped successfully")


if __name__ == "__main__":
    main()
