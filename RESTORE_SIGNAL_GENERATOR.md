# 🛑 URGENT: Restore signal_generator.py

## Problem
The file `app/signals/signal_generator.py` was corrupted during Task 8 integration (only contains `"""`).
This is causing the scanner to crash with:
```
SyntaxError: unterminated triple-quoted string literal (detected at line 1)
```

## Solution: Git Revert (Quick Fix)

Run these commands in your local War-Machine directory:

```bash
# Revert the two bad commits
git revert --no-commit d2a90c32662c7f76f4e67ef6fea10e113a60060e
git revert --no-commit 4a53b8c2110bba0f52755231e3e8f8e9c5fb6076

# This will restore signal_generator.py to the working state
git commit -m "🔧 Restore signal_generator.py to working state"
git push origin main
```

## Alternative: Manual File Restore

If git revert doesn't work, manually restore from the last working commit:

```bash
# Get the file from the last working commit
git checkout e5a437c9c1dfe87f2ddd6ea21dbb12f8cc1ad06c -- app/signals/signal_generator.py

# Commit the restored file
git add app/signals/signal_generator.py
git commit -m "🔧 Restore signal_generator.py from e5a437c9"
git push origin main
```

## Verify Fix

After pushing, Railway will auto-redeploy. Check logs for:
```
[SIGNALS] ✅ Opening Range Detection enabled (Task 7 - OR tight/wide classification)
```

If you see that without syntax errors, the file is restored.

## What Happened?

During Task 8 integration, the GitHub API truncated the file when I tried to update it with the VP/VWAP integration code. The file size limit caused the content to be cut to just `"""` (3 bytes).

## Next Steps After Restore

1. ✅ Verify scanner starts without errors
2. ✅ Volume Profile + VWAP components are already deployed:
   - `app/indicators/volume_profile.py`
   - `app/indicators/vwap_calculator.py`
3. 📝 Follow integration guide in `TASK_8_INTEGRATION.md` to manually add VP/VWAP to signal_generator.py

## Emergency Support

If you need immediate help:
1. Check Railway logs for startup errors
2. The system should work normally once signal_generator.py is restored
3. VP/VWAP integration can be added later (non-critical)

---

**Status**: ⚠️ System down - manual fix required
**ETA**: 2-5 minutes (git revert + redeploy)
**Impact**: Scanner cannot start until file is restored
