# Security

## Supported versions

Only the latest release (`main`) and the current `develop` branch get fixes.

## Reporting a problem

Please don't open a public issue for a security problem. Use GitHub's private reporting instead: the repository's
**Security** tab → **Report a vulnerability**. You'll get an answer there.

## What to look out for

- **Detector databases.** The detector models are stored as skops archives, and the program only loads the
  scikit-learn / NumPy classes a trained model is made of (see `tests/test_model_safety.py`). Small models are stored
  as plain number arrays. Still, only use detector databases from people you trust, and report any way to make the
  program run code from a database or reference file.
- **Screenshots and atlases** are read as images and JSON only.
