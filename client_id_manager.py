"""
Centralized Client ID Manager
Ensures unique client IDs across all scripts to prevent connection conflicts
"""
import os
import json
import time
from pathlib import Path

CLIENT_ID_FILE = Path(__file__).parent / "client_ids.json"
LOCK_FILE = Path(__file__).parent / "client_ids.lock"

# Reserved IDs
RESERVED_IDS = {
    1: "Dashboard (Flask reloader)",
    2: "Dashboard (Flask parent)",
    3: "Quick Status (standalone)"
}

def get_next_available_id():
    """Get next available client ID (thread-safe)"""
    # Wait for lock
    max_wait = 5
    start = time.time()
    while LOCK_FILE.exists():
        if time.time() - start > max_wait:
            LOCK_FILE.unlink(missing_ok=True)
            break
        time.sleep(0.1)
    
    try:
        # Create lock
        LOCK_FILE.touch()
        
        # Load current IDs
        if CLIENT_ID_FILE.exists():
            with open(CLIENT_ID_FILE, 'r') as f:
                data = json.load(f)
        else:
            data = {"in_use": list(RESERVED_IDS.keys()), "counter": 10}
        
        # Get next ID
        client_id = data["counter"]
        data["counter"] += 1
        data["in_use"].append(client_id)
        
        # Save
        with open(CLIENT_ID_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        
        return client_id
        
    finally:
        # Release lock
        LOCK_FILE.unlink(missing_ok=True)

def release_client_id(client_id):
    """Release a client ID when script exits"""
    if client_id in RESERVED_IDS:
        return  # Don't release reserved IDs
    
    # Wait for lock
    max_wait = 5
    start = time.time()
    while LOCK_FILE.exists():
        if time.time() - start > max_wait:
            LOCK_FILE.unlink(missing_ok=True)
            break
        time.sleep(0.1)
    
    try:
        # Create lock
        LOCK_FILE.touch()
        
        # Load current IDs
        if CLIENT_ID_FILE.exists():
            with open(CLIENT_ID_FILE, 'r') as f:
                data = json.load(f)
            
            # Remove ID
            if client_id in data.get("in_use", []):
                data["in_use"].remove(client_id)
            
            # Save
            with open(CLIENT_ID_FILE, 'w') as f:
                json.dump(data, f, indent=2)
                
    finally:
        # Release lock
        LOCK_FILE.unlink(missing_ok=True)

def get_static_id(script_name):
    """
    Get a static client ID for a specific script
    Use this for predictable IDs instead of dynamic allocation
    """
    static_map = {
        "futures_bot_live.py": 10,
        "momentum_auto_switching_live.py": 11,
        "theta_auto_switching_live.py": 12,
        "volatility_auto_switching_live.py": 13,
        "execute_iron_condor_demo.py": 14,
        "run_iron_butterfly.py": 15,
        "run_credit_spread.py": 16,
        "run_butterfly.py": 17,
        "run_futures_ema.py": 18,
        "run_defense_auto.py": 19,
        "close_all_positions.py": 20,
        "run_iron_condor_auto.py": 21,
        "show_risk_metrics.py": 22,
        "analyze_market_conditions.py": 23,
        "select_best_strategy_simple.py": 24,
        "show_position_pnl_chart.py": 25,
        "monitor_account_clean.py": 26,
    }
    
    # Extract just the filename
    filename = os.path.basename(script_name)
    return static_map.get(filename, get_next_available_id())

def cleanup_all():
    """Reset all client IDs (use with caution)"""
    CLIENT_ID_FILE.unlink(missing_ok=True)
    LOCK_FILE.unlink(missing_ok=True)
    print("All client IDs reset")

if __name__ == "__main__":
    # Test
    print("Testing Client ID Manager...")
    print(f"Reserved IDs: {RESERVED_IDS}")
    
    # Test static IDs
    print(f"\nStatic ID for futures_bot_live.py: {get_static_id('futures_bot_live.py')}")
    print(f"Static ID for run_defense_auto.py: {get_static_id('run_defense_auto.py')}")
    
    # Test dynamic allocation
    id1 = get_next_available_id()
    id2 = get_next_available_id()
    print(f"\nDynamic IDs allocated: {id1}, {id2}")
    
    # Test release
    release_client_id(id1)
    print(f"Released ID {id1}")
    
    # Show current state
    if CLIENT_ID_FILE.exists():
        with open(CLIENT_ID_FILE, 'r') as f:
            print(f"\nCurrent state: {json.load(f)}")
