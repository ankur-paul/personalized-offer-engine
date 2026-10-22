# The marketplace runs on a Simulation Clock

All Rules, events and expiries use one global Simulation Clock that only moves when advanced from the console, not wall-clock time. Rules are written in days and weeks (frequency caps, cooldowns, lapse after 45 days, points expiry), so on real time none of them could be demonstrated within a session. Wall-clock time is used only for Telegram delivery mechanics.
