"""Shared playback bounds and common multiplier choices."""
HOTKEYS = {f"F{number}": 0x6F + number for number in range(1, 13)}
MIN_SPEED, MAX_SPEED = 25, 150
SPEED_OPTIONS = (("0.25×", 25), ("0.5×", 50), ("0.75×", 75),
                 ("1.0×", 100), ("1.25×", 125), ("1.5×", 150))
