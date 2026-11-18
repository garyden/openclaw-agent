# test_fetch.py

from town_data_manager import ensure_town_data

ok = ensure_town_data("Edison", "NJ")
print("RESULT:", ok)
