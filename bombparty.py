#!/usr/bin/env python3
"""
BombParty CLI — a single-player terminal version of jklm.fun's BombParty.

Type a word containing the given letter chunk before the bomb explodes.
Run out of lives and the game ends. Use every letter of the alphabet
across all your words to earn a bonus life.

Uses the dwyl/english-words list (auto-downloaded on first run).
"""

import os
import sys
import time
import random
import shutil
import subprocess
import urllib.request
from pathlib import Path
from collections import Counter

# ─── Platform-specific character input ──────────────────────────────────────
if sys.platform == "win32":
    import msvcrt
    os.system("")  # enable ANSI escape codes in Windows terminal

    def getch_nonblocking():
        if msvcrt.kbhit():
            try:
                return msvcrt.getwch()
            except UnicodeDecodeError:
                return None
        return None

    def setup_terminal():
        pass

    def restore_terminal():
        pass
else:
    import termios
    import tty
    import select

    _old_settings = None

    def setup_terminal():
        global _old_settings
        if sys.stdin.isatty():
            _old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())

    def restore_terminal():
        global _old_settings
        if _old_settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _old_settings)
            _old_settings = None

    def getch_nonblocking():
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None


# ─── ANSI colors ────────────────────────────────────────────────────────────
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


# ─── Wordlist management ────────────────────────────────────────────────────
WORDLIST_URL = "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt"
CACHE_DIR = Path.home() / ".bombparty"
CACHE_FILE = CACHE_DIR / "words_alpha.txt"


def _download(url, dest):
    """Try urllib, curl, wget in order. Raises RuntimeError if all fail."""
    errors = []

    # 1. urllib (stdlib, no deps)
    try:
        urllib.request.urlretrieve(url, dest)
        return
    except Exception as e:
        errors.append(f"urllib: {e}")

    # 2. curl (handles certs via the system store)
    if shutil.which("curl"):
        try:
            subprocess.run(
                ["curl", "-fsSL", url, "-o", str(dest)],
                check=True,
                capture_output=True,
            )
            return
        except subprocess.CalledProcessError as e:
            errors.append(f"curl: {e.stderr.decode(errors='ignore').strip() or e}")

    # 3. wget
    if shutil.which("wget"):
        try:
            subprocess.run(
                ["wget", "-q", url, "-O", str(dest)],
                check=True,
                capture_output=True,
            )
            return
        except subprocess.CalledProcessError as e:
            errors.append(f"wget: {e.stderr.decode(errors='ignore').strip() or e}")

    raise RuntimeError("\n  ".join(errors))


def load_wordlist():
    """Download (once) and load the dwyl English wordlist, filtered to 3-15 letter alpha words."""
    if not CACHE_FILE.exists():
        CACHE_DIR.mkdir(exist_ok=True)
        print(f"{C.CYAN}First run: downloading wordlist (~4 MB)...{C.RESET}")
        try:
            _download(WORDLIST_URL, CACHE_FILE)
        except Exception as e:
            print(f"{C.RED}Download failed:{C.RESET}\n  {e}\n")
            print(f"{C.YELLOW}Manual fallback — run this, then re-launch:{C.RESET}")
            print(f"  mkdir -p {CACHE_DIR}")
            print(f"  curl -L {WORDLIST_URL} -o {CACHE_FILE}")
            sys.exit(1)
        print(f"{C.GREEN}Done. Cached at {CACHE_FILE}{C.RESET}\n")
    with open(CACHE_FILE) as f:
        return {
            w.strip().lower()
            for w in f
            if 3 <= len(w.strip()) <= 15 and w.strip().isalpha()
        }


def build_prompts(words, min_matches=80):
    """Return (two_letter_prompts, three_letter_prompts) with at least min_matches words each."""
    counts = Counter()
    for w in words:
        seen = set()
        for n in (2, 3):
            for i in range(len(w) - n + 1):
                chunk = w[i:i + n]
                if chunk not in seen:
                    counts[chunk] += 1
                    seen.add(chunk)
    two = [p for p, c in counts.items() if len(p) == 2 and c >= min_matches]
    three = [p for p, c in counts.items() if len(p) == 3 and c >= min_matches]
    return two, three


# ─── Timed input with live countdown ────────────────────────────────────────
def timed_input(prompt_text, time_limit):
    """
    Read a line of input with a live countdown timer displayed inline.
    Returns (word, time_used) on Enter, or (None, time_limit) on timeout.
    """
    setup_terminal()
    buffer = []
    start = time.time()
    last_remaining = None
    needs_redraw = True
    try:
        while True:
            elapsed = time.time() - start
            remaining = time_limit - elapsed
            if remaining <= 0:
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()
                return None, time_limit

            r_int = int(remaining) + 1
            if r_int != last_remaining or needs_redraw:
                if remaining < 2:
                    color = C.RED + C.BOLD
                elif remaining < 4:
                    color = C.YELLOW
                else:
                    color = C.GREEN
                line = f"\r\033[K{color}[{r_int:2d}s]{C.RESET} {prompt_text}{''.join(buffer)}"
                sys.stdout.write(line)
                sys.stdout.flush()
                last_remaining = r_int
                needs_redraw = False

            ch = getch_nonblocking()
            if ch is None:
                time.sleep(0.03)
                continue
            if ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer), elapsed
            elif ch in ("\x7f", "\b"):  # backspace
                if buffer:
                    buffer.pop()
                    needs_redraw = True
            elif ch == "\x03":  # Ctrl-C
                raise KeyboardInterrupt
            elif ch == "/" or (buffer and buffer[0] == "/"):
                buffer.append(ch)
                needs_redraw = True
            elif ch.isalpha():
                buffer.append(ch.lower())
                needs_redraw = True
            # ignore everything else (arrows, tabs, etc.)
    finally:
        restore_terminal()


# ─── Display helpers ────────────────────────────────────────────────────────
def banner():
    print(f"{C.RED}{C.BOLD}")
    print("  ╔══════════════════════════════════════╗")
    print("  ║       💣  B O M B P A R T Y  💣      ║")
    print("  ║          single-player CLI           ║")
    print("  ╚══════════════════════════════════════╝")
    print(f"{C.RESET}")


def hearts(n):
    if n <= 0:
        return f"{C.DIM}♡♡♡{C.RESET}"
    full = "♥" * min(n, 3)
    empty = "♡" * max(0, 3 - n)
    extra = f" {C.BOLD}+{n - 3}{C.RESET}" if n > 3 else ""
    return f"{C.RED}{full}{C.DIM}{empty}{C.RESET}{extra}"


def alphabet_display(used):
    parts = []
    for c in "abcdefghijklmnopqrstuvwxyz":
        if c in used:
            parts.append(f"{C.GREEN}{C.BOLD}{c}{C.RESET}")
        else:
            parts.append(f"{C.DIM}{c}{C.RESET}")
    return " ".join(parts)


# ─── Main game loop ─────────────────────────────────────────────────────────
def play():
    banner()
    print(f"{C.CYAN}Loading wordlist...{C.RESET}")
    words = load_wordlist()
    two, three = build_prompts(words)
    print(
        f"{C.DIM}Loaded {len(words):,} words │ "
        f"{len(two)} two-letter prompts │ "
        f"{len(three)} three-letter prompts.{C.RESET}\n"
    )

    print(f"{C.WHITE}{C.BOLD}Rules:{C.RESET}")
    print("  • Type a word containing the given letter chunk before time runs out.")
    print("  • Each word must be in the dictionary and unused this game.")
    print("  • Start with 3 lives. Use every letter a-z → bonus life.")
    print(f"  • Commands: {C.YELLOW}/skip{C.RESET} (lose a life), {C.YELLOW}/quit{C.RESET} (end game).\n")
    try:
        input(f"{C.CYAN}Press Enter to start...{C.RESET}")
    except EOFError:
        pass
    print()

    lives = 3
    used_words = set()
    letters_used = set()
    time_limit = 10.0
    round_num = 0
    bonus_count = 0
    longest_word = ""
    total_response_time = 0.0
    successes = 0

    while lives > 0:
        round_num += 1
        # 3-letter prompts get more common as game progresses
        three_chance = min(0.55, 0.20 + round_num * 0.012)
        prompt_pool = three if (three and random.random() < three_chance) else two
        prompt = random.choice(prompt_pool)

        print(
            f"{C.BOLD}─── Round {round_num} ───{C.RESET}  "
            f"{hearts(lives)}  {C.DIM}│{C.RESET} "
            f"timer: {C.YELLOW}{time_limit:.1f}s{C.RESET}  {C.DIM}│{C.RESET} "
            f"words: {C.CYAN}{len(used_words)}{C.RESET}"
        )
        prompt_display = (
            f"Word containing  "
            f"{C.MAGENTA}{C.BOLD}{prompt.upper()}{C.RESET}  →  "
        )

        word, elapsed = timed_input(prompt_display, time_limit)

        if word is None:
            print(f"  {C.RED}{C.BOLD}💥 BOOM! Time's up.{C.RESET}  (-1 ♥)")
            lives -= 1
        elif word in ("/quit", "/q"):
            print(f"  {C.DIM}You bailed.{C.RESET}")
            break
        elif word in ("/skip", "/s"):
            print(f"  {C.YELLOW}Skipped.{C.RESET}  (-1 ♥)")
            lives -= 1
        elif word.startswith("/"):
            print(f"  {C.RED}Unknown command '{word}'.{C.RESET}  (-1 ♥)")
            lives -= 1
        elif not word:
            print(f"  {C.RED}No answer given.{C.RESET}  (-1 ♥)")
            lives -= 1
        elif prompt not in word:
            print(f"  {C.RED}'{word}' doesn't contain '{prompt.upper()}'.{C.RESET}  (-1 ♥)")
            lives -= 1
        elif word not in words:
            print(f"  {C.RED}'{word}' isn't in the dictionary.{C.RESET}  (-1 ♥)")
            lives -= 1
        elif word in used_words:
            print(f"  {C.RED}'{word}' was already used this game.{C.RESET}  (-1 ♥)")
            lives -= 1
        else:
            used_words.add(word)
            new_letters = set(word) - letters_used
            letters_used |= set(word)
            total_response_time += elapsed
            successes += 1
            if len(word) > len(longest_word):
                longest_word = word
            tail = f"  {C.DIM}({elapsed:.1f}s){C.RESET}"
            if new_letters:
                tail += f"  {C.CYAN}+{len(new_letters)} new letter{'s' if len(new_letters) != 1 else ''}{C.RESET}"
            print(f"  {C.GREEN}✓ {word}{C.RESET}{tail}")
            if letters_used >= set("abcdefghijklmnopqrstuvwxyz"):
                lives += 1
                bonus_count += 1
                letters_used.clear()
                print(f"  {C.GREEN}{C.BOLD}🎉 ALPHABET CLEARED! +1 ♥{C.RESET}")
            time_limit = max(3.0, time_limit - 0.15)

        print(f"  {C.DIM}a-z:{C.RESET} {alphabet_display(letters_used)}\n")

    # ─── Game over ──────────────────────────────────────────────────────
    print(f"{C.RED}{C.BOLD}")
    print("  ╔════════════════════════════╗")
    print("  ║         GAME OVER          ║")
    print("  ╚════════════════════════════╝")
    print(f"{C.RESET}")
    avg = (total_response_time / successes) if successes else 0
    longest_display = (
        f"{longest_word} {C.DIM}({len(longest_word)} letters){C.RESET}"
        if longest_word else "—"
    )
    print(f"  Rounds played:       {C.BOLD}{round_num}{C.RESET}")
    print(f"  Words accepted:      {C.BOLD}{len(used_words)}{C.RESET}")
    print(f"  Longest word:        {C.BOLD}{longest_display}{C.RESET}")
    print(f"  Alphabet bonuses:    {C.BOLD}{bonus_count}{C.RESET}")
    print(f"  Avg response time:   {C.BOLD}{avg:.2f}s{C.RESET}")
    print()


if __name__ == "__main__":
    try:
        play()
    except KeyboardInterrupt:
        restore_terminal()
        print(f"\n{C.DIM}Interrupted. Bye.{C.RESET}")
    except Exception:
        restore_terminal()
        raise
