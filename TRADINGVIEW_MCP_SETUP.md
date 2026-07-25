# TradingView MCP — Setup Notes

Setup steps for the [tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp)
server. Committed here so the instructions survive across sessions.

## What it is
An MCP bridge to the **TradingView Desktop** app via Chrome DevTools Protocol
(port 9222). It reads charts, quotes, and Pine scripts. It is **not** a market-data
API and it **cannot place trades** (execution is still the broker's job, e.g.
TradeLocker).

## Important architecture note
This tool must run on the **same machine as the TradingView Desktop app**, driven by
a **local** Claude Code. It cannot be driven from a remote/cloud Claude session
(that container's `localhost` is not your Mac), and it cannot be part of a headless
24/7 server bot (it needs the desktop GUI open with you logged in).

## Install on your Mac
```bash
# 1. Clone + install (needs Node.js: brew install node)
git clone https://github.com/tradesdontlie/tradingview-mcp.git ~/tradingview-mcp
cd ~/tradingview-mcp && npm install

# 2. Register in ~/.claude/.mcp.json  (replace YOUR_USERNAME from `whoami`)
#    {
#      "mcpServers": {
#        "tradingview": {
#          "command": "node",
#          "args": ["/Users/YOUR_USERNAME/tradingview-mcp/src/server.js"]
#        }
#      }
#    }

# 3. Launch TradingView Desktop with remote debugging (quit it first)
/Applications/TradingView.app/Contents/MacOS/TradingView --remote-debugging-port=9222

# 4. Confirm the debug port is up
curl -s http://localhost:9222/json/version

# 5. Run `claude` locally on the Mac, restart it, then run the tv_health_check tool.
#    Expected: { "success": true, "cdp_connected": true, "api_available": true }
```

See `tradingview-mcp/SETUP_GUIDE.md` and `README.md` (78 tools) for full detail.
