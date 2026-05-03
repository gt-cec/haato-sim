import os


def print_debug_header(message):
    """Print a formatted debug header"""
    print("\n" + "=" * 80)
    print(f"DEBUG: {message}")
    print("=" * 80)


def print_debug_info(message, value=None):
    """Print debug information with optional value"""
    if value is not None:
        print(f"[DEBUG] {message}: {value}")
    else:
        print(f"[DEBUG] {message}")


