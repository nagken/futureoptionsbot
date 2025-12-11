#!/usr/bin/env python3
"""
Iron Condor Strategy for Futures Options
Sells OTM call and put spreads to collect premium
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class IronCondorStrategy:
    def __init__(self, config):
        self.config = config
        self.delta_target = config.get('delta_target', 0.15)
        self.wing_width = config.get('wing_width', 10)
        self.target_premium = config.get('target_premium', 100)
        self.profit_target = config.get('profit_target', 0.50)
        self.stop_loss = config.get('stop_loss', 2.0)
        self.dte_target = config.get('days_to_expiration', 7)
        self.dte_close = config.get('dte_close', 2)
        
    def should_enter_trade(self, market_data, current_positions):
        """
        Determine if we should enter a new iron condor
        
        Args:
            market_data: Dict with current price, IV, etc.
            current_positions: List of active positions
            
        Returns:
            bool: True if conditions met for entry
        """
        # Check max positions
        max_positions = self.config.get('max_positions', 3)
        if len(current_positions) >= max_positions:
            logger.info(f"Max positions ({max_positions}) reached")
            return False
        
        # Check IV rank
        iv_rank = market_data.get('iv_rank', 0)
        min_iv_rank = self.config.get('min_iv_rank', 20)
        if iv_rank < min_iv_rank:
            logger.info(f"IV Rank {iv_rank} below minimum {min_iv_rank}")
            return False
        
        # Check market condition
        market_condition = market_data.get('condition', 'neutral')
        target_condition = self.config.get('market_condition', 'neutral')
        if market_condition != target_condition:
            logger.info(f"Market condition {market_condition} not suitable")
            return False
        
        # Check trading hours
        now = datetime.now().time()
        hours = self.config.get('trading_hours', '09:30-15:00').split('-')
        start = datetime.strptime(hours[0], '%H:%M').time()
        end = datetime.strptime(hours[1], '%H:%M').time()
        
        if not (start <= now <= end):
            logger.info("Outside trading hours")
            return False
        
        logger.info("✓ All entry conditions met")
        return True
    
    def calculate_strikes(self, current_price, atm_strike=None):
        """
        Calculate strike prices for iron condor
        
        Args:
            current_price: Current futures price
            atm_strike: At-the-money strike (optional)
            
        Returns:
            dict: Strike prices for all 4 legs
        """
        # If ATM strike provided, use it as reference
        if atm_strike:
            reference = atm_strike
        else:
            reference = round(current_price / 5) * 5  # Round to nearest 5
        
        # Calculate offset based on delta target
        # 15 delta ~ 1 std dev ~ 3-5% for indexes
        offset_pct = 0.03 + (0.15 - self.delta_target) * 0.10
        offset = reference * offset_pct
        
        # Calculate strikes
        call_short = round((reference + offset) / 5) * 5
        call_long = call_short + self.wing_width
        put_short = round((reference - offset) / 5) * 5
        put_long = put_short - self.wing_width
        
        strikes = {
            'call_short': call_short,
            'call_long': call_long,
            'put_short': put_short,
            'put_long': put_long,
            'width': self.wing_width,
            'max_loss': self.wing_width * 5  # MES multiplier is 5
        }
        
        logger.info(f"Calculated strikes: Call {put_short}/{put_long} | Put {call_short}/{call_long}")
        return strikes
    
    def should_exit_position(self, position, current_price, dte):
        """
        Determine if we should exit an existing position
        
        Args:
            position: Position details including entry premium
            current_price: Current option prices
            dte: Days to expiration
            
        Returns:
            tuple: (should_exit, reason)
        """
        entry_premium = position.get('premium_collected', 0)
        current_value = position.get('current_value', 0)
        pnl = entry_premium - current_value
        pnl_pct = pnl / entry_premium if entry_premium > 0 else 0
        
        # Check profit target
        if pnl_pct >= self.profit_target:
            return True, f"Profit target reached: {pnl_pct*100:.1f}%"
        
        # Check stop loss
        if pnl_pct <= -self.stop_loss:
            return True, f"Stop loss hit: {pnl_pct*100:.1f}%"
        
        # Check DTE
        if dte <= self.dte_close:
            return True, f"Close to expiration: {dte} DTE"
        
        # Check if breached (delta adjustment trigger)
        adjustment_trigger = self.config.get('adjustment_trigger', 0.30)
        if position.get('max_delta', 0) >= adjustment_trigger:
            return True, f"Delta breach: {position['max_delta']:.2f}"
        
        return False, "Hold position"
    
    def calculate_position_size(self, account_balance, risk_per_trade):
        """
        Calculate number of contracts to trade
        
        Args:
            account_balance: Current account value
            risk_per_trade: Fraction of account to risk (0.30 = 30%)
            
        Returns:
            int: Number of iron condors to place
        """
        max_risk_per_condor = self.wing_width * 5  # Width × multiplier
        max_risk_allowed = account_balance * risk_per_trade
        
        quantity = int(max_risk_allowed / max_risk_per_condor)
        quantity = max(1, min(quantity, 5))  # Between 1 and 5
        
        logger.info(f"Position size: {quantity} condor(s) | Risk: ${max_risk_per_condor * quantity}")
        return quantity
    
    def get_expiration_date(self, dte=None):
        """
        Get the target expiration date
        
        Args:
            dte: Days to expiration (default from config)
            
        Returns:
            str: Expiration date in YYYYMMDD format
        """
        if dte is None:
            dte = self.dte_target
        
        target_date = datetime.now() + timedelta(days=dte)
        
        # For weekly options, find next Friday
        days_until_friday = (4 - target_date.weekday()) % 7
        if days_until_friday == 0 and target_date.weekday() != 4:
            days_until_friday = 7
        
        expiry_date = target_date + timedelta(days=days_until_friday)
        return expiry_date.strftime('%Y%m%d')
    
    def validate_strikes(self, strikes, option_chain):
        """
        Validate that calculated strikes exist in the option chain
        
        Args:
            strikes: Dict of calculated strikes
            option_chain: Available strikes from broker
            
        Returns:
            bool: True if all strikes are valid
        """
        required_strikes = [
            strikes['call_short'],
            strikes['call_long'],
            strikes['put_short'],
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
        """
        Generate a summary of the proposed trade
        
        Args:
            strikes: Strike prices
            premium: Expected premium to collect
            quantity: Number of contracts
            
        Returns:
            str: Formatted trade summary
        """
        max_profit = premium * quantity
        max_loss = (strikes['width'] * 5 - premium) * quantity
        pop = 85  # Approximate for 15 delta
        
        summary = f"""
╔══════════════════════════════════════════════════╗
║           IRON CONDOR TRADE SUMMARY              ║
╚══════════════════════════════════════════════════╝

  Quantity:        {quantity} contract(s)
  
  CALL SPREAD:     {strikes['call_short']}/{strikes['call_long']}
  PUT SPREAD:      {strikes['put_short']}/{strikes['put_long']}
  Wing Width:      ${strikes['width']}
  
  Premium:         ${max_profit:.2f}
  Max Risk:        ${max_loss:.2f}
  Risk/Reward:     {max_loss/max_profit:.2f}:1
  PoP:             ~{pop}%
  
  Profit Target:   {self.profit_target*100:.0f}% (${max_profit * self.profit_target:.2f})
  Stop Loss:       {self.stop_loss*100:.0f}% (${premium * self.stop_loss:.2f} loss)

════════════════════════════════════════════════════
"""
        return summary


def test_strategy():
    """Test the iron condor strategy"""
    config = {
        'delta_target': 0.15,
        'wing_width': 10,
        'target_premium': 100,
        'profit_target': 0.50,
        'stop_loss': 2.0,
        'days_to_expiration': 7,
        'dte_close': 2,
        'max_positions': 3,
        'min_iv_rank': 20,
        'market_condition': 'neutral',
        'trading_hours': '09:30-15:00'
    }
    
    strategy = IronCondorStrategy(config)
    
    # Test strike calculation
    current_price = 6000
    strikes = strategy.calculate_strikes(current_price)
    print("Strike Calculation Test:")
    print(f"  Current Price: {current_price}")
    print(f"  Strikes: {strikes}")
    
    # Test expiration
    expiry = strategy.get_expiration_date()
    print(f"\nExpiration Date: {expiry}")
    
    # Test position sizing
    quantity = strategy.calculate_position_size(10000, 0.30)
    print(f"\nPosition Size: {quantity} contracts")
    
    # Test trade summary
    summary = strategy.generate_trade_summary(strikes, 100, quantity)
    print(summary)


if __name__ == "__main__":
    test_strategy()
