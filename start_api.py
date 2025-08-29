#!/usr/bin/env python3
"""
Startup script for the Superschedules Navigator API server.

Usage:
    python start_api.py              # Development mode
    python start_api.py --prod       # Production mode
    python start_api.py --port 8080  # Custom port
"""

import argparse
import os
import uvicorn


def main():
    """Start the FastAPI server with configurable options."""
    # Set environment variable for efficient file watching
    os.environ.setdefault("WATCHFILES_FORCE_POLLING", "1")
    parser = argparse.ArgumentParser(description="Start Superschedules Navigator API")
    parser.add_argument(
        "--host", 
        default="0.0.0.0", 
        help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8004, 
        help="Port to bind to (default: 8004)"
    )
    parser.add_argument(
        "--prod", 
        action="store_true", 
        help="Run in production mode (no auto-reload, optimized)"
    )
    parser.add_argument(
        "--workers", 
        type=int, 
        default=1, 
        help="Number of worker processes (default: 1)"
    )
    parser.add_argument(
        "--no-reload", 
        action="store_true", 
        help="Disable auto-reload to reduce CPU usage"
    )
    
    args = parser.parse_args()
    
    if args.prod:
        print(f"🚀 Starting Superschedules Navigator API in PRODUCTION mode")
        print(f"   📍 http://{args.host}:{args.port}")
        print(f"   👷 {args.workers} worker(s)")
        print(f"   🔍 Discovers event navigation patterns on websites")
        
        uvicorn.run(
            "api.main:app",
            host=args.host,
            port=args.port,
            workers=args.workers,
            log_level="info",
            loop="asyncio",
            http="h11"
        )
    else:
        reload_enabled = not args.no_reload
        reload_msg = "🔄 Auto-reload enabled" if reload_enabled else "⚡ Auto-reload DISABLED (lower CPU usage)"
        
        print(f"🔧 Starting Superschedules Navigator API in DEVELOPMENT mode")
        print(f"   📍 http://{args.host}:{args.port}")
        print(f"   {reload_msg}")
        print(f"   📚 API docs: http://{args.host}:{args.port}/docs")
        print(f"   🔍 Discovers event navigation patterns on websites")
        print(f"   ℹ️  Port 8004 avoids conflict with collector (8001) and backend (8000)")
        
        uvicorn_config = {
            "app": "api.main:app",
            "host": args.host,
            "port": args.port,
            "log_level": "debug",
            "loop": "asyncio",
            "http": "h11"
        }
        
        if reload_enabled:
            uvicorn_config.update({
                "reload": True,
                "reload_dirs": ["api"],
                "reload_delay": 1.0
            })
            
        uvicorn.run(**uvicorn_config)


if __name__ == "__main__":
    main()
