#!/usr/bin/env python3
"""Filesystem MCP Connector Wrapper CLI."""

import sys
import os
import json
import pathlib
import argparse

ROOT = pathlib.Path(os.environ.get("SUNEEL_WORKSPACE", str(pathlib.Path.home() / "SuneelWorkSpace"))).resolve()

def list_dir(target_dir: str) -> str:
    p = pathlib.Path(target_dir)
    if not p.is_absolute():
        p = ROOT / target_dir
    try:
        resolved = p.resolve()
        if not str(resolved).startswith(str(ROOT.resolve())) and resolved != ROOT.resolve():
            return json.dumps({"error": f"Access Denied: Path escapes workspace: {target_dir}"})
            
        if not resolved.exists():
            return json.dumps({"error": f"Path not found: {target_dir}"})
            
        entries = []
        for entry in sorted(resolved.iterdir()):
            entries.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size_bytes": entry.stat().st_size if entry.is_file() else None
            })
        return json.dumps(entries, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

def read_file(target_file: str) -> str:
    p = pathlib.Path(target_file)
    if not p.is_absolute():
        p = ROOT / target_file
    try:
        resolved = p.resolve()
        if not str(resolved).startswith(str(ROOT.resolve())):
            return f"Access Denied: Path escapes workspace: {target_file}"
            
        if not resolved.exists():
            return f"File not found: {target_file}"
            
        if resolved.is_dir():
            return f"Error: Path is a directory: {target_file}"
            
        return resolved.read_text(errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"

def main():
    parser = argparse.ArgumentParser(description="Filesystem MCP Tool CLI")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    
    # list parser
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("path", help="Relative or absolute folder path")
    
    # read parser
    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("path", help="Relative or absolute file path")
    
    args = parser.parse_args()
    
    if args.subcommand == "list":
        print(list_dir(args.path))
    elif args.subcommand == "read":
        print(read_file(args.path))
        
if __name__ == "__main__":
    main()
