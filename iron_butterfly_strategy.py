#!/usr/bin/env python3
"""
Iron Butterfly Strategy for Futures Options
Similar to iron condor but with ATM short strikes (more credit, more risk)
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class IronButterflyStrategy:
    def __init__(self, config):
        self.config = config
        self.wing_width = config.get('wing_width', 15)
        self.target_premium = config.get('target_premium', 150)
        self.profit_target = config.get('profit_target', 0.50)
        self.stop_loss = config.get('stop_loss', 1.5)
        self.dte_target = config.get('days_to_expiration', 7)
        self.dte_close = config.get('dte_close', 2)
        
    def should_enter_trade(self, market_data, current_positions):
        """
        Determine if we should enter a new iron butterfly
        
        Iron Butterfly works best in:
        - High IV environments
        - Strong range-bound markets
        - Low volatility expectation
        """
        max_positions = self.config.get('max_positions', 2)
        if len(current_positions) >= max_positions:
            logger.info(f"Max positions ({max_positions}) reached")
            return False
        
        # Need higher IV for butterflies
        iv_rank = market_data.get('iv_rank', 0)
        min_iv_rank = self.config.get('min_iv_rank', 30)
        if iv_rank < min_iv_rank:
            logger.info(f"IV Rank {iv_rank} below minimum {min_iv_rank}")
            return False
        
        # Check for low expected movement
        expected_move = market_data.get('expected_move_pct', 0)
        if expected_move > 0.02:  # More than 2% expected move
            logger.info(f"Expected move too high: {expected_move*100:.1f}%")
            return False
        
        # Check market regime
        regime = market_data.get('regime', 'trending')
        if regime != 'ranging':
            logger.info(f"Market regime '{regime}' not suitable for butterfly")
            return False
        
        # Check trading hours
        now = datetime.now().time()
        hours = self.config.get('trading_hours', '09:30-15:00').split('-')
        start = datetime.strptime(hours[0], '%H:%M').time()
        end = datetime.strptime(hours[1], '%H:%M').time()
        
        if not (start <= now <= end):
            logger.info("Outside trading hours")
            return False
        
        logger.info("✓ All entry conditions met for Iron Butterfly")
        return True
    
    def calculate_strikes(self, current_price):
        """
        Calculate strike prices for iron butterfly
        
        Iron Butterfly structure:
        - Sell ATM call
        - Sell ATM put (same strike)
        - Buy OTM call (protection)
        - Buy OTM put (protection)
        
        Args:
            current_price: Current futures price
            
        Returns:
            dict: Strike prices for all legs
        """
        # ATM strike (same for both call and put)
        atm_strike = round(current_price / 5) * 5
        
        # Wings
        call_long = atm_strike + self.wing_width
        put_long = atm_strike - self.wing_width
        
        strikes = {
            'atm_strike': atm_strike,
            'call_short': atm_strike,
            'call_long': call_long,
            'put_short': atm_strike,
            'put_long': put_long,
            'width': self.wing_width,
            'max_loss': self.wing_width * 5  # MES multiplier
        }
        
        logger.info(f"Iron Butterfly strikes: ATM {atm_strike} | Wings {put_long}/{call_long}")
        return strikes
    
    def should_exit_position(self, position, current_price, dte):
        """
        Determine if we should exit the position
        
        Butterflies are more sensitive to movement, so tighter management
        """
        entry_premium = position.get('premium_collected', 0)
        current_value = position.get('current_value', 0)
        pnl = entry_premium - current_value
        pnl_pct = pnl / entry_premium if entry_premium > 0 else 0
        
        # Take profits quicker on butterflies
        if pnl_pct >= self.profit_target:
            return True, f"Profit target reached: {pnl_pct*100:.1f}%"
        
        # Tighter stop loss
        if pnl_pct <= -self.stop_loss:
            return True, f"Stop loss hit: {pnl_pct*100:.1f}%"
        
        # Check how far price moved from ATM
        atm_strike = position.get('atm_strike', 0)
        price_deviation = abs(current_price - atm_strike)
        wing_width = position.get('wing_width', 0)
        
        # If price moved more than 50% toward wing, consider exit
        if price_deviation > (wing_width * 0.5):
            return True, f"Price deviated {price_deviation} from ATM {atm_strike}"
        
        # Close earlier than iron condor
        if dte <= self.dte_close:
            return True, f"Close to expiration: {dte} DTE"
        
        return False, "Hold position"
    
    def calculate_position_size(self, account_balance, risk_per_trade):
        """
        Calculate number of contracts to trade
        
        Butterflies have higher risk, so use smaller position sizes
        """
        max_risk_per_butterfly = self.wing_width * 5
        max_risk_allowed = account_balance * risk_per_trade
        
        quantity = int(max_risk_allowed / max_risk_per_butterfly)
        quantity = max(1, min(quantity, 3))  # Max 3 butterflies
        
        logger.info(f"Position size: {quantity} butterfly(s) | Risk: ${max_risk_per_butterfly * quantity}")
        return quantity
    
    def get_expiration_date(self, dte=None):
        """Get the target expiration date"""
        if dte is None:
            dte = self.dte_target
        
        target_date = datetime.now() + timedelta(days=dte)
        
        # Find next Friday (weekly options)
        days_until_friday = (4 - target_date.weekday()) % 7
        if days_until_friday == 0 and target_date.weekday() != 4:
            days_until_friday = 7
        
        expiry_date = target_date + timedelta(days=days_until_friday)
        return expiry_date.strftime('%Y%m%d')
    
    def validate_strikes(self, strikes, option_chain):
        """Validate that calculated strikes exist in the option chain"""
        required_strikes = [
            strikes['atm_strike'],
            strikes['call_long'],
            strikes['put_long']
        ]
        
        available_strikes = option_chain.get('strikes', [])
        
        for strike in required_strikes:
            if strike not in available_strikes:
                logger.error(f"Strike {strike} not available in chain")
                return False
        
        logger.info("✓ All strikes validated")
        return True
    
    def generate_trade_summary(self, strikes, premium, quantity):
        """Generate a summary of the proposed trade"""
        max_profit = premium * quantity
        max_loss = (strikes['width'] * 5 - premium) * quantity
        breakeven_upper = strikes['atm_strike'] + (premium / 5)
        breakeven_lower = strikes['atm_strike'] - (premium / 5)
        
        summary = f"""
╔══════════════════════════════════════════════════╗
║         IRON BUTTERFLY TRADE SUMMARY             ║
╚══════════════════════════════════════════════════╝

  Quantity:        {quantity} contract(s)
  
  ATM STRIKE:      {strikes['atm_strike']} (sell call & put)
  CALL WING:       {strikes['call_long']} (buy)
  PUT WING:        {strikes['put_long']} (buy)
  Wing Width:      ${strikes['width']}
  
  Premium:         ${max_profit:.2f}
  Max Risk:        ${max_loss:.2f}
  Risk/Reward:     {max_loss/max_profit:.2f}:1
  
  Breakevens:      {breakeven_lower:.0f} - {breakeven_upper:.0f}
  Profit Zone:     {breakeven_upper - breakeven_lower:.0f} points
  
  Profit Target:   {self.profit_target*100:.0f}% (${max_profit * self.profit_target:.2f})
  Stop Loss:       {self.stop_loss*100:.0f}% (${premium * self.stop_loss:.2f} loss)

  Note: Iron Butterfly collects more premium but has
        narrower profit zone than Iron Condor.
        Best in low-volatility, range-bound markets.

════════════════════════════════════════════════════
"""
        return summary
    
    def compare_to_iron_condor(self, current_price):
        """
        Compare Iron Butterfly vs Iron Condor setup
        
        Helps decide which strategy is better for current market
        """
        butterfly_strikes = self.calculate_strikes(current_price)
        
        # Simulate iron condor with similar setup
        offset = current_price * 0.03
        condor_call = round((current_price + offset) / 5) * 5
        condor_put = round((current_price - offset) / 5) * 5
        
        comparison = f"""
╔══════════════════════════════════════════════════╗
║      BUTTERFLY vs CONDOR COMPARISON              ║
╚══════════════════════════════════════════════════╝

  IRON BUTTERFLY:
    Short Strikes:   {butterfly_strikes['atm_strike']} (ATM)
    Profit Zone:     ±{self.wing_width} points
    Premium:         ~${self.target_premium} (higher)
    Risk:            Higher (ATM exposure)
    Best For:        Range-bound, low movement
  
  IRON CONDOR:
    Short Strikes:   {condor_put}/{condor_call} (OTM)
    Profit Zone:     {condor_call - condor_put} points (wider)
    Premium:         ~$100 (lower)
    Risk:            Lower (OTM buffer)
    Best For:        Neutral trend, moderate movement

════════════════════════════════════════════════════
"""
        return comparison


def test_strategy():
    """Test the iron butterfly strategy"""
    config = {
        'wing_width': 15,
        'target_premium': 150,
        'profit_target': 0.50,
        'stop_loss': 1.5,
        'days_to_expiration': 7,
        'dte_close': 2,
        'max_positions': 2,
        'min_iv_rank': 30,
        'trading_hours': '09:30-15:00'
    }
    
    strategy = IronButterflyStrategy(config)
    
    # Test strike calculation
    current_price = 6000
    strikes = strategy.calculate_strikes(current_price)
    print("Strike Calculation Test:")
    print(f"  Current Price: {current_price}")
    print(f"  Strikes: {strikes}")
    
    # Test trade summary
    summary = strategy.generate_trade_summary(strikes, 150, 2)
    print(summary)
    
    # Test comparison
    comparison = strategy.compare_to_iron_condor(current_price)
    print(comparison)


if __name__ == "__main__":
    test_strategy()
