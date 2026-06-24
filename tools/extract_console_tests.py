import os
import re
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Konfiguration der Pfade
DEFAULT_PATHS = [
    r"C:\Users\gurge\Desktop\RandomStuff\Coding\Genesis Colonies\docs",
    r"C:\Users\gurge\Desktop\RandomStuff\Coding\Genesis Colonies\tests"
]

DANGEROUS_KEYWORDS = [
    "wipe", "delete", "drop", "reset", "truncate", 
    "rm ", "del ", "rmdir", "migration", "migrate"
]

CATEGORIES = {
    "Pytest": r"pytest",
    "Economy": r"economy|market|resource|trade",
    "Queue": r"queue|task|job",
    "Frontend/Static": r"frontend|static|react|vue|ui",
    "Fleet": r"fleet|ship|combat|travel",
    "Research": r"research|tech|science",
    "Buildings": r"building|construct|structure",
    "Scripts": r"scripts/|tools/",
    "Misc": r"."
}

def get_category(command):
    cmd_lower = command.lower()
    for cat, pattern in CATEGORIES.items():
        if re.search(pattern, cmd_lower):
            return cat
    return "Misc"

def is_dangerous(command):
    cmd_lower = command.lower()
    return any(kw in cmd_lower for kw in DANGEROUS_KEYWORDS)

def extract_commands(file_path):
    commands = []
    # Regex für gängige Python/Pytest Befehle
    pattern = re.compile(r"((?:python -m )?pytest\s+\S+|(?:python\s+)?(?:scripts|tools)/\S+\.py\S*)")
    
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, 1):
                matches = pattern.findall(line)
                for match in matches:
                    clean_cmd = match.strip().strip('`').strip('"')
                    if clean_cmd:
                        commands.append({
                            "command": clean_cmd,
                            "line": i,
                            "file": str(file_path)
                        })
    except Exception as e:
        print(f"Fehler beim Lesen von {file_path}: {e}")
    return commands

def main():
    parser = argparse.ArgumentParser(description="Genesis Console Test Extractor")
    parser.add_argument("--docs", type=str, help="Pfad zum Docs Ordner")
    parser.add_argument("--tests", type=str, help="Pfad zum Tests Ordner")
    parser.add_argument("--category", type=str, help="Nur bestimmte Kategorie extrahieren")
    parser.add_argument("--include-dangerous", action="store_true", help="Gefährliche Befehle in PS1 aufnehmen")
    args = parser.parse_args()

    search_paths = []
    if args.docs: search_paths.append(Path(args.docs))
    if args.tests: search_paths.append(Path(args.tests))
    if not search_paths:
        search_paths = [Path(p) for p in DEFAULT_PATHS if os.path.exists(p)]

    found_entries = []
    for path in search_paths:
        for ext in ["*.md", "*.py"]:
            for file in path.rglob(ext):
                found_entries.extend(extract_commands(file))

    # Filtern nach Kategorie falls gewünscht
    if args.category:
        found_entries = [e for e in found_entries if get_category(e['command']).lower() == args.category.lower()]

    unique_commands = {} # command -> first_entry
    report_data = []

    for entry in found_entries:
        cmd = entry['command']
        cat = get_category(cmd)
        dangerous = is_dangerous(cmd)
        
        report_data.append({**entry, "category": cat, "dangerous": dangerous})
        
        if dangerous and not args.include_dangerous:
            continue
            
        if cmd not in unique_commands:
            unique_commands[cmd] = cat

    # PowerShell File erzeugen
    with open("console_tests_latest.ps1", "w", encoding="utf-8") as ps:
        ps.write("$failures = @()\n")
        ps.write('Write-Host "Genesis Console Tests" -ForegroundColor Cyan\n')
        ps.write('Write-Host "=====================" -ForegroundColor Cyan\n\n')
        
        for i, (cmd, cat) in enumerate(unique_commands.items(), 1):
            ps.write(f'Write-Host "[{i}] {cat}: {cmd[:60]}..." -ForegroundColor Yellow\n')
            ps.write(f"{cmd}\n")
            ps.write("if ($LASTEXITCODE -ne 0) { $failures += \"Line $i: $cmd\" }\n\n")

        ps.write('if ($failures.Count -gt 0) {\n')
        ps.write('  Write-Host "FAILED COMMANDS:" -ForegroundColor Red\n')
        ps.write('  $failures | ForEach-Object { Write-Host " - $_" }\n')
        ps.write('  exit 1\n')
        ps.write('} else {\n')
        ps.write('  Write-Host "ALL TESTS PASSED" -ForegroundColor Green\n')
        ps.write('}\n')

    # Report File erzeugen
    with open("console_tests_report.txt", "w", encoding="utf-8") as rep:
        rep.write(f"Genesis Test Report - {datetime.now()}\n")
        rep.write("="*50 + "\n\n")
        
        for entry in report_data:
            cat = "SKIPPED_DANGEROUS" if entry['dangerous'] else entry['category']
            rep.write(f"[{cat}]\n")
            rep.write(f"Source: {entry['file']}:{entry['line']}\n")
            rep.write(f"Command: {entry['command']}\n")
            rep.write("-" * 20 + "\n")

    print(f"Extraktion abgeschlossen. {len(unique_commands)} Befehle in PS1, {len(report_data)} Fundstellen im Report.")

if __name__ == "__main__":
    main()
