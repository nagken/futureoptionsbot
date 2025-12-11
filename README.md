# Futures Options Trading Bot

Automated trading bot for MES/MNQ futures options using Iron Condor and Iron Butterfly strategies.

## Features

- **Iron Condor Strategy**: Sell OTM call and put spreads for consistent income
- **Iron Butterfly Strategy**: Sell ATM options with wings for higher premium
- **Risk Management**: Position sizing, stop loss, profit targets
- **IBKR Integration**: Direct connection to Interactive Brokers TWS/Gateway
- **Real-time Monitoring**: Track positions, P&L, and Greeks

## Quick Start

### 1. Prerequisites
- Python 3.8+
- Interactive Brokers account (paper or live)
- TWS or IB Gateway running

### 2. Installation

```bash
# Clone or download this repository
cd dec10futbotoptions

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

```bash
# Copy environment template
copy .env.template .env

# Edit .env with your IBKR credentials
notepad .env
```

Update these values in `.env`:
```
IBKR_USERNAME=your_username
IBKR_PASSWORD=your_password
IBKR_PORT=7496
IBKR_TRADING_MODE=paper
```

### 4. Configure Strategy

Edit `10_config/config_options_bot.yaml` to customize:
- Strike selection (delta targets)
- Wing width
- Position sizing
- Risk parameters
- Entry/exit rules

### 5. Run the Bot

**Windows:**
```bash
Start_Options_Bot.bat
```

**Python:**
```bash
python futures_options_bot.py
```

## Strategies

### Iron Condor
- Sells OTM call and put spreads
- Best for neutral markets
- 15 delta targets (85% probability of profit)
- Lower premium, wider profit zone

### Iron Butterfly
- Sells ATM call and put
- Best for range-bound markets
- Higher premium collected
- Narrower profit zone, more risk

## File Structure

```
dec10futbotoptions/
├── futures_options_bot.py          # Main bot
├── iron_condor_strategy.py         # Iron Condor logic
├── iron_butterfly_strategy.py      # Butterfly logic
├── client_id_manager.py            # IBKR client ID management
├── Start_Options_Bot.bat           # Launcher script
├── .env.template                   # Environment template
├── requirements.txt                # Python dependencies
└── 10_config/
    └── config_options_bot.yaml     # Strategy configuration
```

## Risk Management

The bot includes multiple safety features:
- Maximum position limits
- Daily loss limits
- Stop loss on individual positions
- Profit targets
- Time-based exits (DTE management)
- Position monitoring

## Important Notes

⚠️ **Always start with paper trading**
⚠️ **Test thoroughly before using real money**
⚠️ **Monitor positions regularly**
⚠️ **Understand max loss on each trade**

## Configuration Examples

### Conservative Setup (Default)
```yaml
max_positions: 2
risk_per_trade: 0.20
profit_target: 0.50
stop_loss: 1.5
```

### Aggressive Setup
```yaml
max_positions: 5
risk_per_trade: 0.40
profit_target: 0.40
stop_loss: 2.0
```

## Monitoring

The bot logs all activity to `options_bot.log` and displays:
- Current positions
- P&L (daily and total)
- Entry/exit signals
- Risk metrics

## Troubleshooting

**Connection Issues:**
- Verify TWS/Gateway is running
- Check port in .env matches TWS settings
- Enable API access in TWS (Configure > API > Settings)
- Check firewall settings

**No Trades Executing:**
- Verify entry conditions in config
- Check IV rank requirements
- Confirm trading hours
- Check max position limits

**Data Issues:**
- Ensure market data subscriptions are active
- Verify futures permissions in IBKR account
- Check option chain availability

## Support & Resources

- IBKR API Documentation: https://ibkrcampus.com/ibkr-api-page/
- Options Strategy Guide: See strategy modules
- Configuration Reference: See config YAML files

## License

For personal use only. Use at your own risk.
